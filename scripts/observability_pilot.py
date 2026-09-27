"""One healthy event in a fresh dedicated Kind environment; bounded, no retries."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_environment as env
from scripts.a1_flow import Observations, ObservedVerifier, tunnel
from scripts.a1_runtime import Config as RuntimeConfig
from scripts.a1_runtime import Runtime
from scripts.scale_calibration import verify_images, wait_api
from scripts.scale_contract import CLUSTER, RUNTIME_CONFIG, SOURCE, utc, write
from scripts.scale_diagnostic import TimedTransport
from scripts.verify_flow import Config, Failure, HttpTransport

EXPECTED_CLUSTER = "fulfillflow-observe-01"
WORKERS = ("core-worker", "tracking-worker", "notifications-worker")
FIELDS = {
    "timestamp",
    "service",
    "stage",
    "outcome",
    "duration_ms",
    "category",
    "message_id",
    "event_id",
    "correlation_id",
    "request_id",
    "attempts",
    "generation",
}


def guard(minimum):
    battery = psutil.sensors_battery()
    available = psutil.virtual_memory().available / 1024**3
    if battery is not None and not battery.power_plugged:
        raise RuntimeError("HOST_ON_BATTERY")
    if available < minimum:
        raise RuntimeError("HOST_MEMORY_BELOW_GUARD")
    return {"utc": utc(), "available_gib": available, "required_gib": minimum}


def project_logs(text):
    rows, ignored = [], 0
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except (ValueError, TypeError):
            ignored += 1
            continue
        if not isinstance(row, dict) or not all(
            k in row for k in ("timestamp", "stage", "outcome", "service")
        ):
            ignored += 1
            continue
        # Never retain unrecognized text, bodies, URLs or exception messages.
        rows.append({k: row[k] for k in FIELDS if k in row})
    return {"records": rows, "ignored_lines": ignored, "raw_logs_retained": False}


def pod_identities(private, evidence=None, timeout=30):
    pods = json.loads(env.kubectl(private, ["get", "pods", "-o", "json"], timeout=timeout))["items"]
    if evidence is not None:
        snapshot = []
        for pod in pods:
            name = pod["metadata"].get("labels", {}).get("app.kubernetes.io/name")
            if name in WORKERS:
                statuses = pod.get("status", {}).get("containerStatuses", [])
                snapshot.append(
                    {
                        "worker": name,
                        "uid": pod["metadata"]["uid"],
                        "phase": pod.get("status", {}).get("phase"),
                        "deleting": bool(pod["metadata"].get("deletionTimestamp")),
                        "containers": [
                            {
                                "ready": c.get("ready"),
                                "restart_count": c.get("restartCount"),
                                "state": list(c.get("state", {})),
                            }
                            for c in statuses
                        ],
                    }
                )
        with evidence.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"utc": utc(), "workers": snapshot}) + "\n")
    result = {}
    for name in WORKERS:
        matching = [
            p for p in pods if p["metadata"].get("labels", {}).get("app.kubernetes.io/name") == name
        ]
        if len(matching) != 1:
            raise RuntimeError("WORKER_NOT_UNIQUE")
        pod = matching[0]
        statuses = pod.get("status", {}).get("containerStatuses", [])
        if (
            pod["metadata"].get("deletionTimestamp")
            or len(statuses) != 1
            or not statuses[0].get("ready")
            or not isinstance(statuses[0].get("restartCount"), int)
        ):
            raise RuntimeError("WORKER_NOT_STABLE")
        result[name] = {
            "name": pod["metadata"]["name"],
            "uid": pod["metadata"]["uid"],
            "restart_count": statuses[0]["restartCount"],
        }
    return result


def wait_workers(private, evidence, *, samples=61, sleep=time.sleep):
    previous, stable = None, 0
    deadline = time.monotonic() + 120
    for index in range(samples):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            current = pod_identities(private, evidence, timeout=min(10, remaining))
        except RuntimeError as error:
            if str(error) not in ("WORKER_NOT_STABLE", "WORKER_NOT_UNIQUE"):
                raise
            previous, stable = None, 0
        else:
            stable = stable + 1 if current == previous else 1
            previous = current
            if stable >= 3:
                return current
        if index + 1 < samples:
            sleep(max(0, min(2, deadline - time.monotonic())))
    raise RuntimeError("WORKER_STARTUP_TIMEOUT")


def resume_identity(private, source):
    # Only the diagnosed pre-offer failure is resumable; never replay a business event.
    if (private / "observability-resume.claim").exists():
        raise RuntimeError("RESUME_ALREADY_CLAIMED")
    protocol = json.loads((source / "protocol.json").read_bytes())
    if protocol.get("infrastructure_sha") != "e1a46246012acbb858c049e60b7048c4b67524b3":
        raise RuntimeError("UNREVIEWED_RESUME_REFERENCE")
    if json.loads((source / "flow-error.json").read_bytes()) != {"error": "WORKER_NOT_STABLE"}:
        raise RuntimeError("RESUME_NOT_PREFLOW_FAILURE")
    if any(
        (source / name).exists()
        for name in ("event", "functional.json", "http-timings.json", "flow-summary.json")
    ):
        raise RuntimeError("RESUME_MAY_HAVE_OFFERED")
    if not json.loads((source / "shutdown.json").read_bytes()).get("container_stopped"):
        raise RuntimeError("RESUME_SHUTDOWN_UNCONFIRMED")
    bootstrap = json.loads((source / "bootstrap/bootstrap.json").read_bytes())
    identity = json.loads((private / "identity.json").read_bytes())
    if (
        not bootstrap.get("complete")
        or bootstrap.get("namespace_uid") != identity.get("namespace_uid")
        or identity.get("source") != SOURCE
    ):
        raise RuntimeError("RESUME_BOOTSTRAP_IDENTITY")
    node = json.loads(env.command(["docker", "inspect", CLUSTER + "-control-plane"]))[0]
    if (
        node["Id"] != identity["container_id"]
        or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER
        or node["State"]["Running"]
    ):
        raise RuntimeError("RESUME_NODE_IDENTITY")
    if env.command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    return bootstrap


def new_window_identity(private, source):
    result = json.loads((source / "inspection.json").read_bytes())
    summary = json.loads((source / "summary.json").read_bytes())
    if (
        result.get("query_status") != 200
        or result.get("finding") != "no_record_returned"
        or not summary.get("container_stopped")
    ):
        raise RuntimeError("INSPECTION_NOT_REVIEWED")
    if (private / "healthy-window-02.claim").exists():
        raise RuntimeError("WINDOW_ALREADY_CLAIMED")
    identity = json.loads((private / "identity.json").read_bytes())
    if identity.get("source") != SOURCE or identity.get("image_id") != env.IMAGE_ID:
        raise RuntimeError("APPLICATION_IDENTITY")
    node = json.loads(env.command(["docker", "inspect", CLUSTER + "-control-plane"]))[0]
    if (
        node["Id"] != identity["container_id"]
        or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER
        or node["State"]["Running"]
    ):
        raise RuntimeError("NODE_IDENTITY")
    if env.command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    return {
        "source": SOURCE,
        "namespace_uid": identity["namespace_uid"],
        "prior_event_id": result["event_id"],
    }


def check_forwarding(verifier):
    # Fresh verifier identity: this GET cannot replay the prior uncertain admission.
    from urllib.parse import urlencode

    verifier.phase = "forwarding_preflight"
    result = verifier.get(
        "/api/v1/carrier-events?"
        + urlencode(
            {
                "external_event_id": verifier.event_id,
                "carrier_code": "carrier-alpha",
                "page": 1,
                "page_size": 2,
            }
        )
    )
    if result.get("items") != [] or type(result.get("total")) is not int or result["total"] != 0:
        raise Failure("FORWARDING_PREFLIGHT_SCHEMA")
    verifier.evidence.emit("forwarding_preflight_passed", event_id=verifier.event_id)
    verifier.phase = "prepare"


def flow(private, output):
    identity = json.loads((private / "identity.json").read_bytes())
    node = json.loads(env.command(["docker", "inspect", CLUSTER + "-control-plane"]))[0]
    if (
        node["Id"] != identity["container_id"]
        or node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER
    ):
        raise RuntimeError("NODE_IDENTITY")
    env.command(["docker", "start", node["Id"]])
    wait_api(private)
    for name in ("core", "tracking", "notifications", *WORKERS):
        env.kubectl(
            private, ["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130
        )
    verify_images(private, identity)
    ns = json.loads(env.kubectl(private, ["get", "namespace", "fulfillflow", "-o", "json"]))
    if ns["metadata"]["uid"] != identity["namespace_uid"]:
        raise RuntimeError("NAMESPACE_IDENTITY")
    before = wait_workers(private, output / "worker-startup.jsonl")
    tool, _ = env.tools()
    config = RuntimeConfig(
        str(tool),
        env.executable("docker"),
        str(private / "kubeconfig"),
        "kind-" + CLUSTER,
        "fulfillflow",
        identity["namespace_uid"],
        CLUSTER + "-control-plane",
        env.IMAGE,
        RUNTIME_CONFIG,
        flow_seconds=120,
    )
    config.validate()
    runtime = Runtime(config)
    values = json.loads((private / "values.json").read_bytes())
    started = utc()
    transport = TimedTransport(HttpTransport())
    error = None
    result = {}
    try:
        with tunnel(runtime) as (url, _):
            until = time.monotonic() + 30
            while time.monotonic() < until:
                try:
                    if HttpTransport()("GET", url + "/health/ready", {}, None, 2).status == 200:
                        break
                except Failure:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("CORE_API_NOT_READY")
            evidence = Observations(output / "event")
            flow_config = Config(
                url, output / "event", secret=values["alpha"], deadline_seconds=120
            )
            flow_config.validate()
            verifier = ObservedVerifier(flow_config, evidence, transport)
            try:
                evidence.emit("started", event_id=verifier.event_id, unique_events=1)
                check_forwarding(verifier)
                order, shipment, code = verifier.prepare()
                raw, headers = verifier.webhook(code)
                inbox, location = verifier.admit(raw, headers)
                event = verifier.tracking(inbox, location, shipment)
                verifier.final_business(order, shipment)
                notification = verifier.notifications(event)
                verifier.effects(shipment, inbox, event, notification)
            except Failure as failure:
                error = failure.code
            except Exception as failure:
                error = type(failure).__name__
                raise
            finally:
                result = verifier.summary(error is None, error)
                result["checkpoint"] = evidence.checkpoint
                evidence.close()
                write(output / "functional.json", result)
    finally:
        write(output / "http-timings.json", transport.records)
        capture = {}
        for name, pod in before.items():
            text = env.kubectl(
                private,
                ["logs", pod["name"], "--since-time=" + started, "--limit-bytes=2000000"],
                timeout=30,
            )
            if len(text.encode("utf-8")) >= 2000000:
                raise RuntimeError("LOG_CAPTURE_LIMIT")
            capture[name] = {"pod": pod, **project_logs(text)}
            write(output / (name + "-records.json"), capture[name])
        write(output / "worker-records.json", capture)
        if pod_identities(private) != before:
            raise RuntimeError("WORKER_IDENTITY_CHANGED")
    write(
        output / "flow-summary.json",
        {
            "functional_success": result.get("success", False),
            "capture_finished": True,
            "structured_records_per_worker": {
                name: len(data["records"]) for name, data in capture.items()
            },
            "coverage_requires_review": True,
            "tracing_tested": False,
            "source": SOURCE,
            "planned_unique_events": 1,
            "webhook_offered": result.get("webhook_offered", False),
        },
    )
    if error:
        raise RuntimeError("FUNCTIONAL_CHECK_FAILED")


def terminate_child(child):
    # Stop only the process tree started by this executor, including port-forward.
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"], capture_output=True, timeout=20
        )
    else:
        for descendant in psutil.Process(child.pid).children(recursive=True):
            descendant.kill()
        child.kill()
    child.wait(timeout=20)


def stage(name, private, output):
    child = subprocess.Popen(
        [
            sys.executable,
            __file__,
            "--private",
            str(private),
            "--output",
            str(output),
            "--stage",
            name,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + (45 * 60 if name == "bootstrap" else 15 * 60)
    try:
        with (output / (name + "-host.jsonl")).open("x", encoding="utf-8") as stream:
            while child.poll() is None:
                sample = guard(2)
                sample["executor_rss_bytes"] = psutil.Process().memory_info().rss
                stream.write(json.dumps(sample) + "\n")
                stream.flush()
                if time.monotonic() >= deadline:
                    raise RuntimeError("STAGE_DEADLINE")
                time.sleep(2)
        if child.returncode:
            raise RuntimeError("STAGE_FAILED_" + name.upper())
    finally:
        if child.poll() is None:
            terminate_child(child)


def execute(private, output, resume_from=None, new_window_from=None):
    if CLUSTER != EXPECTED_CLUSTER:
        raise RuntimeError("OBSERVABILITY_ENVIRONMENT_REQUIRED")
    if (
        (private.exists() and resume_from is None and new_window_from is None)
        or output.exists()
        or private.is_relative_to(env.ROOT)
    ):
        raise RuntimeError("EXCLUSIVE_PATHS_REQUIRED")
    host = guard(5)
    facts = (
        new_window_identity(private, new_window_from)
        if new_window_from
        else resume_identity(private, resume_from)
        if resume_from
        else env.preflight()
    )
    output.mkdir(parents=True, exist_ok=False)
    write(
        output / "protocol.json",
        {
            "host": host,
            "runtime": facts,
            "infrastructure_sha": env.command(["git", "rev-parse", "HEAD"]).strip(),
            "unique_events": 1,
            "resumed_from": resume_from.name if resume_from else None,
            "new_window_after": new_window_from.name if new_window_from else None,
            "mode": "healthy-existing-worker-logs",
            "autoscaling": False,
            "tracing": False,
        },
    )
    if resume_from:
        write(private / "observability-resume.claim", {"output": output.name, "utc": utc()})
    if new_window_from:
        write(private / "healthy-window-02.claim", {"output": output.name, "utc": utc()})
    complete, error = False, None
    stopped = False
    try:
        if resume_from is None and new_window_from is None:
            print("Observability: fresh environment (historical volumes preserved)", flush=True)
            stage("bootstrap", private, output)
        else:
            print(
                "Observability: existing dedicated environment; bootstrap preserved",
                flush=True,
            )
        guard(2)
        print("Observability: one healthy event and three worker logs", flush=True)
        stage("flow", private, output)
        complete = True
    except Exception as failure:
        error = str(failure) if isinstance(failure, RuntimeError) else type(failure).__name__
    finally:
        # This exact cluster was absent at preflight; never stop a different node.
        try:
            nodes = json.loads(env.command(["docker", "inspect", CLUSTER + "-control-plane"]))
            if nodes[0]["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER:
                raise RuntimeError("CLEANUP_IDENTITY")
            env.command(["docker", "stop", "--timeout", "30", nodes[0]["Id"]], timeout=60)
            stopped = not json.loads(env.command(["docker", "inspect", nodes[0]["Id"]]))[0][
                "State"
            ]["Running"]
        except Exception:
            complete = False
            error = error or "SHUTDOWN_NOT_CONFIRMED"
        write(output / "shutdown.json", {"container_stopped": stopped, "volumes_preserved": True})
        write(
            output / "summary.json",
            {
                "complete": complete,
                "error": error,
                "container_stopped": stopped,
                "tracing_tested": False,
            },
        )
    print(
        json.dumps(
            {
                "complete": complete,
                "error": error,
                "output": str(output),
                "container_stopped": stopped,
            }
        )
    )
    return 0 if complete else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stage", choices=("bootstrap", "flow", "inspect"))
    parser.add_argument("--resume-from", type=Path)
    parser.add_argument("--new-window-from", type=Path)
    args = parser.parse_args()
    private, output = args.private.resolve(), args.output.resolve()
    try:
        if CLUSTER != EXPECTED_CLUSTER:
            raise RuntimeError("OBSERVABILITY_ENVIRONMENT_REQUIRED")
        if args.stage == "bootstrap":
            env.bootstrap(private, output / "bootstrap")
        elif args.stage == "flow":
            flow(private, output)
        elif args.stage == "inspect":
            from scripts.observability_inspect import inspect_event

            inspect_event(private, output)
        else:
            lock = env.ROOT / "artifacts/observability-pilot.lock"
            lock.parent.mkdir(parents=True, exist_ok=True)
            with lock.open("x"):
                pass
            try:
                return execute(
                    private,
                    output,
                    args.resume_from.resolve() if args.resume_from else None,
                    args.new_window_from.resolve() if args.new_window_from else None,
                )
            finally:
                lock.unlink()
    except Exception as failure:
        code = str(failure) if isinstance(failure, RuntimeError) else type(failure).__name__
        if args.stage and output.is_dir():
            write(output / (args.stage + "-error.json"), {"error": code})
        print(json.dumps({"complete": False, "error": code}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
