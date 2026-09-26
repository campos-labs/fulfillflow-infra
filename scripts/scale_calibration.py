"""Two fixed-replica calibration runs; never installs an autoscaler or repeats evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_environment as environment
from scripts import scale_observation as telemetry
from scripts.scale_contract import (
    CLUSTER,
    QUERY,
    RUNTIME_CONFIG,
    SOURCE,
    TARGET,
    metric,
    outcome,
    schedule,
    utc,
    write,
)
from scripts.verify_flow import Config, Evidence, Failure, HttpTransport, Verifier

ROOT = environment.ROOT


def records(path):
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines(keepends=True) if line.endswith("\n")]


def load_journal_finished(records):
    # This marker is flushed after every response. Process exit alone races a prior read.
    return any(record.get("kind") == "load_finished" for record in records)


def identity(private):
    expected = json.loads((private / "identity.json").read_text())
    node = json.loads(environment.command(["docker", "inspect", CLUSTER + "-control-plane"]))[0]
    if (
        node["Id"] != expected["container_id"]
        or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER
    ):
        raise RuntimeError("CONTAINER_IDENTITY")
    if expected["source"] != SOURCE:
        raise RuntimeError("SOURCE_IDENTITY")
    return expected


def db_metric(private, password):
    # Restricted role over TCP; password enters stdin only, never command arguments.
    shell = "IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -h 127.0.0.1 -U scale_observer -d fulfillflow_core -At -v ON_ERROR_STOP=1"
    text = environment.kubectl(
        private,
        ["exec", "-i", "postgres-0", "--", "sh", "-c", shell],
        password + "\n" + QUERY,
        timeout=10,
    )
    return metric(json.loads(text))


def verify_images(private, expected):
    if expected.get("image_id") != environment.IMAGE_ID:
        raise RuntimeError("IMPORTED_IMAGE_IDENTITY")
    pods = json.loads(environment.kubectl(private, ["get", "pods", "-o", "json"]))["items"]
    seen = set()
    for pod in pods:
        name = pod["metadata"]["labels"].get("app.kubernetes.io/name", "")
        if name not in (
            "core",
            "tracking",
            "notifications",
            "core-worker",
            "tracking-worker",
            "notifications-worker",
        ):
            continue
        statuses = pod["status"].get("containerStatuses", [])
        if not statuses:
            raise RuntimeError("RUNTIME_IMAGE_UNOBSERVED")
        seen.add(name)
        for container in statuses:
            if RUNTIME_CONFIG != container.get("imageID", "").removeprefix("docker-pullable://"):
                raise RuntimeError("RUNTIME_IMAGE_IDENTITY")

    if seen != {
        "core",
        "tracking",
        "notifications",
        "core-worker",
        "tracking-worker",
        "notifications-worker",
    }:
        raise RuntimeError("RUNTIME_INCOMPLETE")


def observe(v, item, *, reuse_terminal_reads=False):
    v.deadline = time.monotonic() + 20
    state = {"event_id": item["event_id"], "observed_monotonic": time.monotonic()}
    try:
        path = "/api/v1/carrier-events/" + item["inbox_id"]
        inbox = v.get(path)
        if inbox.get("external_event_id") != item["event_id"]:
            raise Failure("EVENT_IDENTITY")
        if inbox.get("status") == "REJECTED" or inbox.get("progress") == "BLOCKED_LOCAL":
            return {**state, "terminal_failure": True}
        if inbox.get("status") != "PROCESSED":
            return {**state, "pending_confirmed": True, "stage": "tracking"}
        event = v.tracking(
            item["inbox_id"],
            path,
            item["shipment_id"],
            **({"initial_record": inbox} if reuse_terminal_reads else {}),
        )
        v.final_business(item["order_id"], item["shipment_id"])
        status = v.get("/api/v1/notification-status/" + event)
        if status.get("status") == "FAILED" or "BLOCKED" in (
            status.get("publication"),
            status.get("processing"),
        ):
            return {**state, "terminal_failure": True}
        if status.get("processing") != "DONE":
            return {**state, "pending_confirmed": True, "stage": "notifications"}
        notification = v.notifications(
            event, **({"initial_record": status} if reuse_terminal_reads else {})
        )
        v.effects(item["shipment_id"], item["inbox_id"], event, notification)
        return {
            **state,
            "completed_monotonic": time.monotonic(),
            "effects_unique": True,
            "tracking_event_id": event,
            "notification_id": notification,
        }
    except Failure as error:
        return {**state, "observation_error": error.code}


def run_one(
    private,
    folder,
    replicas,
    settings,
    values,
    base,
    expected,
    work_deadline,
    policy=None,
    diagnostic=False,
    reuse_terminal_reads=False,
):
    if reuse_terminal_reads and not diagnostic:
        raise RuntimeError("REUSE_REQUIRES_DIAGNOSTIC")
    folder.mkdir(exist_ok=False)
    if diagnostic:
        from scripts.scale_diagnostic import TimedTransport, throttling_sample
    environment.kubectl(private, ["scale", "deployment/" + TARGET, "--replicas=" + str(replicas)])
    environment.kubectl(
        private, ["rollout", "status", "deployment/" + TARGET, "--timeout=90s"], timeout=100
    )
    verify_images(private, expected)
    if db_metric(private, values["observer"])["eligible"]:
        raise RuntimeError("INITIAL_BACKLOG")
    before = telemetry.wait_worker_count(private, replicas)
    prepared = []
    verifiers = {}
    offsets = schedule(
        settings["stages"], characterization=settings.get("capacity_characterization", False)
    )
    for index in range(len(offsets)):
        if time.monotonic() >= work_deadline:
            raise RuntimeError("OPERATIONAL_WINDOW_EXHAUSTED")
        evidence = Evidence(folder / f"event-{index:04d}")
        v = Verifier(
            Config(base, folder, deadline_seconds=120, secret=values["alpha"]),
            evidence,
            HttpTransport(),
        )
        v.deadline = min(v.deadline, work_deadline)
        order, shipment, code = v.prepare()
        prepared.append(
            {
                "event_id": v.event_id,
                "order_id": order,
                "shipment_id": shipment,
                "tracking_code": code,
            }
        )
        if diagnostic:
            v.transport = TimedTransport(v.transport)
        verifiers[v.event_id] = v
    write(folder / "prepared.json", prepared)
    write(folder / "load.json", {"base": base, **settings})
    child_env = {**os.environ, "CARRIER_ALPHA_WEBHOOK_SECRET": values["alpha"]}
    results = {}
    admissions = {}
    if policy:
        policy.begin_load(private, folder)

    def collect():
        sample = telemetry.temporal_sample(
            private, replicas, lambda: db_metric(private, values["observer"])
        )
        if diagnostic:
            sample["throttling"] = throttling_sample(private)
            sample["collection_end_monotonic"] = time.monotonic()
        return policy.sample(private, sample) if policy else sample

    collector = telemetry.Collector(
        folder / "series.jsonl",
        collect,
        settings["collection_interval_seconds"],
    )
    collector.start()
    since = utc()
    started = time.monotonic()
    child_log = (folder / "load-process.log").open("x", encoding="utf-8")
    try:
        child = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/scale_load.py"), str(folder)],
            env=child_env,
            stdout=child_log,
            stderr=subprocess.STDOUT,
            cwd=ROOT,
        )
    except Exception:
        child_log.close()
        collector.close()
        raise
    try:
        deadline = (
            started
            + sum(s["seconds"] for s in settings["stages"])
            + settings["observation_seconds"]
            + 30
        )
        with ThreadPoolExecutor(max_workers=16) as observers:
            while time.monotonic() < min(deadline, work_deadline):
                tick = time.monotonic()
                incoming = records(folder / "admission.jsonl")
                admissions = {
                    r["event_id"]: r
                    for r in incoming
                    if r["kind"] == "response" and r["status"] == 202
                }
                eligible = []
                for item in prepared:
                    event = item["event_id"]
                    admission = admissions.get(event)
                    if (
                        not admission
                        or "inbox_id" not in admission
                        or results.get(event, {}).get("completed_monotonic")
                    ):
                        continue
                    if time.monotonic() - admission["monotonic"] > settings["observation_seconds"]:
                        continue
                    eligible.append({**item, "inbox_id": admission["inbox_id"]})
                observed = list(
                    observers.map(
                        lambda item: observe(
                            verifiers[item["event_id"]],
                            item,
                            reuse_terminal_reads=reuse_terminal_reads,
                        ),
                        eligible,
                    )
                )
                for record in observed:
                    results[record["event_id"]] = record
                if collector.failed.is_set():
                    raise RuntimeError("COLLECTION_FAILED")
                if any(r.get("terminal_failure") for r in observed):
                    raise RuntimeError("BUSINESS_FAILURE")
                if child.poll() is not None and child.returncode != 0:
                    raise RuntimeError("LOAD_PROCESS_FAILED")
                if (
                    child.poll() is not None
                    and load_journal_finished(incoming)
                    and len(results) == len(admissions)
                    and all(r.get("completed_monotonic") for r in results.values())
                ):
                    break
                time.sleep(
                    max(0, settings["collection_interval_seconds"] - (time.monotonic() - tick))
                )
        child.wait(timeout=15)
        incoming = records(folder / "admission.jsonl")
        final = []
        for item in prepared:
            event = item["event_id"]
            admission = admissions.get(event)
            result = results.get(event, {})
            if admission:
                classification = outcome(
                    admission["monotonic"],
                    result.get("completed_monotonic"),
                    settings["functional_deadline_seconds"],
                    bool(result.get("observation_error")),
                    result.get("pending_confirmed", False),
                )
            else:
                offered = any(
                    x.get("event_id") == event and x["kind"] == "offered" for x in incoming
                )
                responses = [
                    x for x in incoming if x.get("event_id") == event and x["kind"] == "response"
                ]
                classification = (
                    "not_offered"
                    if not offered
                    else "not_accepted"
                    if responses and 400 <= responses[-1]["status"] < 500
                    else "acceptance_unknown"
                )
            final.append(
                {**item, **result, "classification": classification, "acceptance": admission}
            )
        write(folder / "events.json", final)
        counts = {
            name: sum(x["classification"] == name for x in final)
            for name in sorted({x["classification"] for x in final})
        }
        collector.close()
        if collector.failed.is_set():
            raise RuntimeError("COLLECTION_FAILED")
        distribution = (
            policy.attribution(private, admissions, folder / "worker-attribution.json")
            if policy
            else telemetry.attribution(
                private, before, since, admissions, folder / "worker-attribution.json"
            )
        )
        final_metric = db_metric(private, values["observer"])
        passed = distribution["complete"] and all(
            x["classification"] in ("completed_in_time", "completed_late") for x in final
        )
        write(
            folder / "summary.json",
            {
                "complete": True,
                "functional_passed": all(
                    x["classification"] in ("completed_in_time", "completed_late") for x in final
                ),
                "attribution_complete": distribution["complete"],
                "per_pod_completed": distribution["per_pod"],
                "counts": counts,
                "initial_fixed_replicas": replicas,
                "final_inbox": final_metric,
                "latencies_are_observed_upper_bounds": True,
                "observer_concurrency": 16,
                "reuse_terminal_reads": reuse_terminal_reads,
                "instrument": "Locust HttpSession; open arrival schedule; kubelet/SQL temporal collection",
            },
        )
        return passed
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=15)
        child_log.close()
        collector.close()
        for v in verifiers.values():
            if diagnostic:
                write(
                    Path(v.evidence.stream.name).with_name("http-timings.json"), v.transport.records
                )
            v.evidence.close()


def wait_api(private, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            if (
                environment.kubectl(
                    private, ["get", "--raw", "/readyz", "--request-timeout=5s"], timeout=7
                ).strip()
                == "ok"
            ):
                return
        except (RuntimeError, subprocess.TimeoutExpired):
            pass
        time.sleep(2)
    raise RuntimeError("KUBERNETES_API_STARTUP_TIMEOUT")


def _execute(
    private,
    output,
    extension=None,
    diagnostic=False,
    reuse_terminal_reads=False,
    controlled_host=False,
    peak_rate=8,
    http_concurrency=8,
):
    if controlled_host and (not diagnostic or not reuse_terminal_reads):
        raise RuntimeError("CONTROLLED_REFERENCE_REQUIRES_REUSE_DIAGNOSTIC")
    if reuse_terminal_reads and not diagnostic:
        raise RuntimeError("REUSE_REQUIRES_DIAGNOSTIC")
    if diagnostic and extension:
        raise RuntimeError("DIAGNOSTIC_NOT_AUTOSCALING")
    expected = identity(private)
    if output.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    if environment.command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    if environment.command(["git", "status", "--porcelain"], timeout=10).strip():
        raise RuntimeError("DIRTY_CHECKOUT")
    work_deadline = time.monotonic() + 100 * 60
    settings = json.loads((ROOT / "config/scale-calibration.json").read_text())
    schedule(settings["stages"], characterization=settings.get("capacity_characterization", False))
    if settings["replicas"] != [1, 2] or settings["http_concurrency"] != 8:
        raise RuntimeError("CALIBRATION_CONFIGURATION_CHANGED")
    from scripts.scale_diagnostic import characterization_settings

    settings = characterization_settings(
        settings,
        peak_rate,
        diagnostic=diagnostic,
        reuse=reuse_terminal_reads,
        controlled=controlled_host,
        extension=extension,
        http_concurrency=http_concurrency,
    )
    if peak_rate != 8:
        work_deadline = time.monotonic() + 20 * 60
    output.mkdir(parents=True)
    write(
        output / "protocol.json",
        {
            "source": SOURCE,
            "infrastructure_sha": environment.command(["git", "rev-parse", "HEAD"]).strip(),
            "settings": settings,
            "identity": expected,
            "runtime_config_digest": RUNTIME_CONFIG,
            "purpose": "fixed-one instrumentation diagnostic"
            if diagnostic
            else "KEDA bounded pilot"
            if extension
            else "calibration only",
            "diagnostic": {
                "enabled": diagnostic,
                "fixed_replicas": 1 if diagnostic else None,
                "load_changed": peak_rate != 8,
                "peak_rate": peak_rate,
                "admission_concurrency_changed": http_concurrency != 8,
                "controlled_host": controlled_host,
                "reuse_terminal_reads": reuse_terminal_reads,
            },
            **(
                {"policy": extension.pin, "prepare_only": extension.prepare_only}
                if extension
                else {}
            ),
        },
    )
    values = json.loads((private / "values.json").read_text())
    port = 18181
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))
    tunnel = None
    host = None
    if controlled_host:
        from scripts.scale_host import HostMonitor

        host = HostMonitor(output)
    try:
        if host:
            host.start()
        environment.command(["docker", "start", CLUSTER + "-control-plane"])
        wait_api(private)
        environment.kubectl(
            private,
            ["wait", "--for=condition=Ready", "nodes", "--all", "--timeout=120s"],
            timeout=130,
        )
        ns = json.loads(
            environment.kubectl(private, ["get", "namespace", "fulfillflow", "-o", "json"])
        )
        if ns["metadata"]["uid"] != expected["namespace_uid"]:
            raise RuntimeError("NAMESPACE_IDENTITY")
        for name in (
            "core",
            "tracking",
            "notifications",
            "core-worker",
            "tracking-worker",
            "notifications-worker",
        ):
            environment.kubectl(
                private, ["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130
            )
        tool, _ = environment.tools()
        tunnel_args = [
            str(tool),
            "--kubeconfig",
            str(private / "kubeconfig"),
            "--context",
            "kind-" + CLUSTER,
            "-n",
            "fulfillflow",
            "port-forward",
            "--address",
            "127.0.0.1",
            "service/core",
            f"{port}:8000",
        ]
        base = f"http://127.0.0.1:{port}"
        # A restarted kubelet can report cached Ready before the target container runs.
        # Retry only the local tunnel before offering any workload, preserving diagnostics.
        until = time.monotonic() + 90
        with (output / "tunnel-startup.log").open("x", encoding="utf-8") as tunnel_log:
            while time.monotonic() < until:
                if tunnel is None or tunnel.poll() is not None:
                    tunnel = subprocess.Popen(
                        tunnel_args, stdout=tunnel_log, stderr=subprocess.STDOUT
                    )
                try:
                    response = HttpTransport()("GET", base + "/health/ready", {}, None, 2)
                    if response.status == 200 and tunnel.poll() is None:
                        break
                except Failure:
                    pass
                time.sleep(2)
            else:
                raise RuntimeError("TUNNEL_NOT_READY")
        if diagnostic:
            from scripts.scale_diagnostic import require_fixed_target, wait_throttling

            require_fixed_target(private)
            print(
                "Diagnostic: waiting for throttling metrics (startup only, up to 90 seconds)",
                flush=True,
            )
            write(
                output / "throttling-preflight.json",
                wait_throttling(private, output / "throttling-startup.jsonl"),
            )
            event_count = len(
                schedule(
                    settings["stages"],
                    characterization=settings.get("capacity_characterization", False),
                )
            )
            print(
                f"Diagnostic: {event_count} events, one fixed replica, throttling and HTTP timing",
                flush=True,
            )
            if not run_one(
                private,
                output / "fixed-1",
                1,
                settings,
                values,
                base,
                expected,
                work_deadline,
                diagnostic=True,
                reuse_terminal_reads=reuse_terminal_reads,
            ):
                raise RuntimeError("DIAGNOSTIC_FUNCTIONAL_OR_ATTRIBUTION_INCOMPLETE")
        elif extension:
            extension.run(private, output, settings, values, base, expected, work_deadline)
        else:
            for count in settings["replicas"]:
                print(f"Calibration: {count} fixed replica(s)", flush=True)
                if not run_one(
                    private,
                    output / f"fixed-{count}",
                    count,
                    settings,
                    values,
                    base,
                    expected,
                    work_deadline,
                ):
                    raise RuntimeError("CALIBRATION_NOT_COMPLETE")
        write(
            output / "summary.json",
            {
                "complete": True,
                "autoscaling_tested": bool(extension and not extension.prepare_only),
                "next": "pause for pilot review"
                if extension
                else "review fixed-replica signal and headroom before KEDA integration",
            },
        )
    except Exception as error:
        if not (output / "summary.json").exists():
            write(
                output / "summary.json",
                {
                    "complete": False,
                    "error": type(error).__name__,
                    "code": str(error)
                    if isinstance(error, RuntimeError)
                    else "CALIBRATION_INTERRUPTED",
                },
            )
        raise
    finally:
        if tunnel and tunnel.poll() is None:
            tunnel.terminate()
            tunnel.wait(timeout=10)
        cleanup_error = None
        if extension:
            try:
                extension.cleanup(private)
            except Exception as error:
                cleanup_error = type(error).__name__
                write(output / "controller-cleanup-error.json", {"error": cleanup_error})
        stopped = False
        try:
            environment.command(
                ["docker", "stop", "--timeout", "30", CLUSTER + "-control-plane"], timeout=60
            )
            state = json.loads(
                environment.command(["docker", "inspect", CLUSTER + "-control-plane"])
            )[0]
            stopped = not state["State"]["Running"]
        finally:
            write(
                output / "shutdown.json", {"container_stopped": stopped, "volumes_preserved": True}
            )
            if (not stopped or cleanup_error) and (output / "summary.json").exists():
                summary = json.loads((output / "summary.json").read_text())
                summary["complete"] = False
                summary["shutdown_error"] = True
                (output / "summary.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
            host_result = host.close() if host else None
            if host_result and not host_result["valid"] and (output / "summary.json").exists():
                summary = json.loads((output / "summary.json").read_text())
                summary["complete"] = False
                summary["host_conditions_valid"] = False
                (output / "summary.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
        hashes = []
        for path in sorted(output.rglob("*")):
            if path.is_file():
                hashes.append(
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    + "  "
                    + path.relative_to(output).as_posix()
                )
        (output / "checksums.sha256").write_text("\n".join(hashes) + "\n", encoding="utf-8")
        if cleanup_error:
            raise RuntimeError("CONTROLLER_CLEANUP_FAILED")
        if not stopped:
            raise RuntimeError("NODE_SHUTDOWN_UNCONFIRMED")
        if host_result and not host_result["valid"]:
            raise RuntimeError("HOST_CONDITIONS_NOT_VALIDATED")


@contextmanager
def exclusive(private):
    if not private.is_dir():
        raise RuntimeError("PRIVATE_DIRECTORY_UNAVAILABLE: " + str(private))
    lock = private / "calibration.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def execute(
    private,
    output,
    diagnostic=False,
    reuse_terminal_reads=False,
    controlled_host=False,
    peak_rate=8,
    http_concurrency=8,
):
    if private.is_relative_to(output) or output.is_relative_to(private):
        raise RuntimeError("PRIVATE_OUTPUT_OVERLAP")
    with exclusive(private):
        _execute(
            private,
            output,
            diagnostic=diagnostic,
            reuse_terminal_reads=reuse_terminal_reads,
            controlled_host=controlled_host,
            peak_rate=peak_rate,
            http_concurrency=http_concurrency,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--reuse-terminal-reads", action="store_true")
    parser.add_argument("--controlled-host", action="store_true")
    parser.add_argument("--peak-rate", type=int, choices=(8, 12, 16), default=8)
    parser.add_argument("--http-concurrency", type=int, choices=(8, 16), default=8)
    args = parser.parse_args()
    try:
        execute(
            args.private.resolve(),
            args.output.resolve(),
            diagnostic=args.diagnostic,
            reuse_terminal_reads=args.reuse_terminal_reads,
            controlled_host=args.controlled_host,
            peak_rate=args.peak_rate,
            http_concurrency=args.http_concurrency,
        )
        print(
            json.dumps(
                {
                    "complete": True,
                    "autoscaling_tested": False,
                    "output": str(args.output.resolve()),
                }
            )
        )
    except Exception as error:
        detail = {"complete": False, "error": type(error).__name__}
        if isinstance(error, FileNotFoundError):
            detail["missing"] = Path(error.filename).name if error.filename else "unidentified"
        elif isinstance(error, RuntimeError):
            detail["code"] = str(error)
        print(json.dumps(detail))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
