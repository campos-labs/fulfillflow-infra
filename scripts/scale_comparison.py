"""Prospective comparison: isolated state, common windows and no outcome-driven retries."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import random
import statistics
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_calibration as cal
from scripts import scale_environment as env
from scripts import scale_observation as obs
from scripts.scale_contract import CLUSTER, TARGET, utc, write
from scripts.scale_host import snapshot
from scripts.scale_keda import NAME, Pilot, apply, get, k, scaled_object

ROOT = env.ROOT
CONFIG = ROOT / "config/scale-comparison.json"
CONDITIONS = ("fixed-1", "fixed-2", "adaptive")
OWNERS = ("core", "tracking", "notifications")
WORKLOADS = (*OWNERS, *(x + "-worker" for x in OWNERS))
CAMPAIGN_CLUSTER = "fulfillflow-scale-compare-01"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def config():
    value = json.loads(CONFIG.read_text())
    if value != {
        "version": 1,
        "seed": 260927,
        "blocks": 3,
        "http_concurrency": 32,
        "stages": [
            {"seconds": 15, "rate": 2},
            {"seconds": 60, "rate": 16},
            {"seconds": 15, "rate": 2},
        ],
        "functional_deadline_seconds": 60,
        "observation_seconds": 120,
        "window_seconds": 450,
        "collection_interval_seconds": 5,
        "max_sampling_gap_seconds": 10,
        "attempt_minutes": 20,
    }:
        raise RuntimeError("COMPARISON_PROTOCOL_CHANGED")
    return value


def order(seed):
    rng = random.Random(seed)
    labels = list(CONDITIONS)
    rng.shuffle(labels)
    blocks = [labels[i:] + labels[:i] for i in range(3)]
    rng.shuffle(blocks)
    return blocks


def require_context():
    if (
        CLUSTER != CAMPAIGN_CLUSTER
        or os.environ.get("FULFILLFLOW_SCALE_ENVIRONMENT") != "comparison-v1"
    ):
        raise RuntimeError("COMPARISON_CLUSTER_REQUIRED")


def assert_owned(private):
    require_context()
    expected = cal.identity(private)
    ns = json.loads(env.kubectl(private, ["get", "namespace", "fulfillflow", "-o", "json"]))
    if ns["metadata"]["uid"] != expected["namespace_uid"]:
        raise RuntimeError("NAMESPACE_IDENTITY")
    return expected


def sql(private, owner, text):
    if owner not in (*OWNERS, "postgres"):
        raise RuntimeError("DATABASE_NOT_ALLOWED")
    database = "postgres" if owner == "postgres" else "fulfillflow_" + owner
    return env.kubectl(
        private,
        [
            "exec",
            "-i",
            "postgres-0",
            "--",
            "psql",
            "-X",
            "-U",
            "postgres",
            "-d",
            database,
            "-At",
            "-v",
            "ON_ERROR_STOP=1",
        ],
        text,
        timeout=90,
    )


def runtime(private, replicas):
    assert_owned(private)
    for name in WORKLOADS:
        env.kubectl(private, ["scale", "deployment/" + name, "--replicas=" + str(replicas)])
    end = time.monotonic() + 150
    if replicas == 0:
        while time.monotonic() < end:
            pods = json.loads(env.kubectl(private, ["get", "pods", "-o", "json"]))["items"]
            if not any(
                p["metadata"].get("labels", {}).get("app.kubernetes.io/name") in WORKLOADS
                for p in pods
            ):
                return
            time.sleep(2)
        raise RuntimeError("RUNTIME_QUIESCENCE_TIMEOUT")
    for name in WORKLOADS:
        env.kubectl(
            private, ["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130
        )


def queues(private):
    data = json.loads(
        env.kubectl(
            private,
            [
                "exec",
                "rabbitmq-0",
                "--",
                "rabbitmqctl",
                "list_queues",
                "-q",
                "-p",
                "fulfillflow-v13",
                "name",
                "messages",
                "--formatter=json",
            ],
            timeout=30,
        )
    )
    if not isinstance(data, list) or any(type(r.get("messages")) is not int for r in data):
        raise RuntimeError("QUEUE_STATE_UNKNOWN")
    return data


def empty_queues(private):
    data = queues(private)
    if any(r["messages"] for r in data):
        raise RuntimeError("PENDING_BROKER_STATE_PRESERVED")
    return data


def save_databases(private, folder):
    assert_owned(private)
    folder.mkdir(exist_ok=False)
    hashes = {}
    for owner in OWNERS:
        data = env.kubectl(
            private,
            [
                "exec",
                "postgres-0",
                "--",
                "pg_dump",
                "-U",
                "postgres",
                "--format=p",
                "--encoding=UTF8",
                "fulfillflow_" + owner,
            ],
            timeout=90,
        )
        path = folder / (owner + ".sql")
        path.write_text(data, encoding="utf-8", newline="\n")
        hashes[owner] = digest(path)
    write(folder / "hashes.json", hashes)
    return hashes


def template_hashes(private):
    hashes = {}
    for kind, names in (("deployment", WORKLOADS), ("statefulset", ("postgres", "rabbitmq"))):
        for name in names:
            obj = json.loads(env.kubectl(private, ["get", kind + "/" + name, "-o", "json"]))
            hashes[kind + "/" + name] = hashlib.sha256(
                json.dumps(obj["spec"]["template"], sort_keys=True).encode()
            ).hexdigest()
    return hashes


def baseline(private):
    identity = assert_owned(private)
    marker = json.loads((private / "comparison-baseline.json").read_text())
    if marker["identity"] != identity or marker["protocol_sha256"] != digest(CONFIG):
        raise RuntimeError("BASELINE_IDENTITY")
    if marker["templates"] != template_hashes(private):
        raise RuntimeError("RUNTIME_TEMPLATE_CHANGED")
    for owner in OWNERS:
        if digest(private / "baseline" / (owner + ".sql")) != marker["hashes"][owner]:
            raise RuntimeError("BASELINE_HASH")
    return marker


def restore(private, output):
    marker = baseline(private)
    if (
        get(private, "scaledobject", NAME)
        or json.loads(env.kubectl(private, ["get", "hpa", "-o", "json"]))["items"]
    ):
        raise RuntimeError("CONTROLLER_BEFORE_RESTORE")
    runtime(private, 0)
    empty_queues(private)
    # Destructive SQL is restricted to three databases on the separately identified campaign cluster.
    for owner in OWNERS:
        database = "fulfillflow_" + owner
        sql(
            private,
            "postgres",
            f'DROP DATABASE "{database}"; CREATE DATABASE "{database}" OWNER "{database}";',
        )
        sql(private, owner, (private / "baseline" / (owner + ".sql")).read_text(encoding="utf-8"))
    write(
        output / "initial-state.json",
        {
            "baseline_hashes": marker["hashes"],
            "queues": empty_queues(private),
            "restored": True,
            "utc": utc(),
        },
    )
    runtime(private, 1)


def inventory(private):
    data = json.loads(
        env.kubectl(
            private,
            ["get", "pods", "-l", "app.kubernetes.io/name=" + TARGET, "-o", "json"],
            timeout=10,
        )
    )["items"]
    return {
        "observed_monotonic": time.monotonic(),
        "pods": [
            {
                "uid": p["metadata"]["uid"],
                "name": p["metadata"]["name"],
                "created_at": p["metadata"]["creationTimestamp"],
                "deleting_at": p["metadata"].get("deletionTimestamp"),
                "phase": p.get("status", {}).get("phase"),
                "ready": any(
                    c.get("type") == "Ready" and c.get("status") == "True"
                    for c in p.get("status", {}).get("conditions", [])
                ),
            }
            for p in data
        ],
    }


def pod_time(samples, start, end):
    rows = [r["pod_inventory"] for r in samples]
    times = [r["observed_monotonic"] for r in rows]
    if (
        not rows
        or times[0] > start
        or times[-1] < end
        or any(b <= a or b - a > 10 for a, b in itertools.pairwise(times))
    ):
        raise RuntimeError("POD_TIME_COVERAGE")
    result = {
        "existing_pod_seconds": 0.0,
        "running_pod_seconds": 0.0,
        "ready_pod_seconds": 0.0,
        "terminating_pod_seconds": 0.0,
    }
    for a, b in itertools.pairwise(rows):
        duration = max(0, min(end, b["observed_monotonic"]) - max(start, a["observed_monotonic"]))
        pods = a["pods"]
        result["existing_pod_seconds"] += duration * len(pods)
        result["running_pod_seconds"] += duration * sum(p["phase"] == "Running" for p in pods)
        result["ready_pod_seconds"] += duration * sum(p["ready"] for p in pods)
        result["terminating_pod_seconds"] += duration * sum(
            p["deleting_at"] is not None for p in pods
        )
    return {
        **result,
        "window_seconds": end - start,
        "max_gap_seconds": max(b - a for a, b in itertools.pairwise(times)),
        "method": "left-step estimate from sampled inventory; existing includes terminating; not exact lifecycle duration or monetary cost",
    }


def judge(events, admission, attribution, samples):
    counts = {
        c: sum(e["classification"] == c for e in events)
        for c in sorted({e["classification"] for e in events})
    }
    accepted = [e for e in events if e.get("acceptance")]
    issues = []
    if len(events) != 1020 or counts.get("not_offered"):
        issues.append("OFFER_INCOMPLETE")
    if any(
        e["classification"] == "acceptance_unknown"
        or (e.get("acceptance") and "inbox_id" not in e["acceptance"])
        for e in events
    ):
        issues.append("ACCEPTANCE_UNKNOWN")
    if not cal.load_journal_finished(admission):
        issues.append("LOAD_JOURNAL_INCOMPLETE")
    if any(not r["controller"]["metric"]["available"] for r in samples):
        issues.append("METRIC_UNAVAILABLE")
    if attribution.get("log_gaps"):
        issues.append("ATTRIBUTION_LOG_GAP")
    if any(
        p["restarts"] != attribution["restart_baseline"].get(p["uid"], 0)
        for p in attribution["pods"]
    ):
        issues.append("WORKER_RESTART")
    recs = attribution["records"]
    for e in accepted:
        rid = e["acceptance"].get("request_id")
        n = sum(r["request_id"] == rid for r in recs)
        if n > 1 or (e["classification"] in ("completed_in_time", "completed_late") and n != 1):
            issues.append("ATTRIBUTION_MISMATCH")
            break
    # Pending, late, explicit business failure and observation inconclusion remain outcomes.
    on_time = counts.get("completed_in_time", 0)
    return {
        "execution_valid": not issues,
        "invalid_reasons": issues,
        "counts": counts,
        "planned": len(events),
        "accepted": len(accepted),
        "confirmed_in_time": on_time,
        "confirmed_in_time_fraction": on_time / len(accepted) if accepted else None,
        "outcome_limit": "inconclusive is unknown, pending is last observed state, neither means lost",
    }


class Trial(Pilot):
    formal_comparison = True

    def __init__(self, condition):
        if condition not in CONDITIONS:
            raise RuntimeError("CONDITION_NOT_ALLOWED")
        super().__init__(capacity_profile=True, sustained_profile=True)
        self.condition = condition
        self.fixed = 2 if condition == "fixed-2" else 1

    def validate_invocation(self, rate, concurrency, seconds, replicas):
        require_context()
        config()
        if (rate, concurrency, seconds, replicas) != (16, 32, 60, 1):
            raise RuntimeError("FORMAL_PROFILE_NOT_ALLOWED")

    def capacity_settings(self, settings):
        result = super().capacity_settings(settings)
        return {
            **result,
            "functional_deadline_seconds": config()["functional_deadline_seconds"],
            "observation_seconds": config()["observation_seconds"],
            "collection_interval_seconds": config()["collection_interval_seconds"],
            "formal_comparison": True,
            "http_concurrency": 32,
            "purpose": "prospective three-condition comparison",
            "replicas": [self.fixed],
        }

    def prepare_environment(self, private, output, expected):
        self.guard("baseline_restore")
        restore(private, output)
        self.guard("baseline_restored")

    def activate(self, private):
        if (
            get(private, "scaledobject", NAME)
            or json.loads(k(private, ["get", "hpa", "-o", "json"]))["items"]
        ):
            raise RuntimeError("EXISTING_SCALE_CONTROLLER")
        obj = scaled_object(self.pin)
        if self.condition != "adaptive":
            obj["spec"]["minReplicaCount"] = self.fixed
            obj["spec"]["maxReplicaCount"] = self.fixed
        apply(private, obj)
        self.object_uid = get(private, "scaledobject", NAME)["metadata"]["uid"]

    def begin_load(self, private, folder):
        for owner in OWNERS:
            sql(private, owner, "ANALYZE;")
        super().begin_load(private, folder)
        # Same bounded stabilization and health reads for all three conditions, no business warm-up.
        end = time.monotonic() + 30
        while time.monotonic() < end:
            self.guard("stabilization")
            status = self.status(private)
            if not status["metric"]["available"]:
                raise RuntimeError("METRIC_UNAVAILABLE_BEFORE_LOAD")
            time.sleep(5)
        if len(obs.worker_pods(private)) != self.fixed:
            raise RuntimeError("INITIAL_WORKER_COUNT")
        obj = get(private, "scaledobject", NAME)
        write(folder / "actual-controller.json", obj["spec"])

    def sample(self, private, sample):
        result = super().sample(private, sample)
        result["condition"] = self.condition
        result["pod_inventory"] = inventory(private)
        return result

    def run(self, private, output, settings, values, base, expected, deadline):
        self.install(private, output)
        from scripts.scale_diagnostic import wait_throttling

        write(
            output / "throttling-preflight.json",
            wait_throttling(private, output / "throttling-startup.jsonl"),
        )
        print(
            "Comparison: " + self.condition + ", 1020 events, common 450-second window", flush=True
        )
        cal.run_one(
            private,
            output / "measurement",
            self.fixed,
            settings,
            values,
            base,
            expected,
            deadline,
            policy=self,
            diagnostic=True,
            reuse_terminal_reads=True,
            host_guard=self.guard,
        )
        self.guard("measurement_finished")
        review_trial(output)
        if not json.loads((output / "comparison-result.json").read_text())["execution_valid"]:
            raise RuntimeError("COMPARISON_EXECUTION_INVALID")

    def preserve_end(self, private, output):
        runtime(private, 0)
        folder = private / "trial-states" / output.name
        folder.parent.mkdir(exist_ok=True)
        hashes = save_databases(private, folder)
        write(
            output / "preserved-state.json",
            {
                "hashes": hashes,
                "queues": queues(private),
                "location": "private trial-states directory; not public evidence",
            },
        )


def review_trial(output):
    folder = output / "measurement"

    def read(f):
        return json.loads((folder / f).read_text())

    samples = cal.records(folder / "series.jsonl")
    result = judge(
        read("events.json"),
        cal.records(folder / "admission.jsonl"),
        read("worker-attribution.json"),
        samples,
    )
    window = read("window.json")
    try:
        result["pod_time"] = pod_time(samples, window["start"], window["end"])
    except RuntimeError:
        result["execution_valid"] = False
        result["invalid_reasons"].append("POD_TIME_COVERAGE")
    admissions = cal.records(folder / "admission.jsonl")
    events = read("events.json")
    latencies = sorted(
        e["completed_monotonic"] - e["acceptance"]["monotonic"]
        for e in events
        if e.get("completed_monotonic") and e.get("acceptance")
    )
    offered = {r["event_id"]: r["monotonic"] for r in admissions if r["kind"] == "offered"}
    durations = sorted(
        r["monotonic"] - offered[r["event_id"]]
        for r in admissions
        if r["kind"] == "response" and r["event_id"] in offered
    )

    def timing(values):
        return {
            "count": len(values),
            "median": statistics.median(values) if values else None,
            "p95": values[math.ceil(0.95 * len(values)) - 1] if values else None,
            "max": max(values) if values else None,
        }

    result["confirmation_observed_seconds"] = timing(latencies)
    result["admission_http_seconds"] = timing(durations)
    result["max_active_requests"] = max(
        (r["active_requests"] for r in admissions if r["kind"] == "dispatch_attempt"), default=0
    )
    result["max_eligible"] = max(r["inbox"]["eligible"] for r in samples)
    result["max_oldest_eligible_seconds"] = max(
        r["inbox"]["oldest_eligible_seconds"] for r in samples
    )
    result["observed_confirmation_drain_seconds"] = max(
        0,
        max(
            (e["completed_monotonic"] for e in events if e.get("completed_monotonic")),
            default=window["start"],
        )
        - window["start"]
        - 90,
    )
    result["drain_censored"] = any(
        e["classification"]
        not in ("completed_in_time", "completed_late", "not_accepted", "not_offered")
        for e in events
    )
    result["condition"] = samples[0]["condition"]
    result["protocol_sha256"] = digest(CONFIG)
    write(output / "comparison-result.json", result)
    return result


def prepare(private, output):
    require_context()
    config()
    if output.exists() or private.exists():
        raise RuntimeError("FRESH_CAMPAIGN_REQUIRED")
    env.bootstrap(private, output)
    env.command(["docker", "start", CLUSTER + "-control-plane"])
    pilot = Pilot()
    try:
        cal.wait_api(private)
        for name in ("postgres", "rabbitmq"):
            env.kubectl(
                private, ["rollout", "status", "statefulset/" + name, "--timeout=180s"], timeout=190
            )
        pilot.install(private, output)
        runtime(private, 0)
        empty_queues(private)
        hashes = save_databases(private, private / "baseline")
        marker = {
            "identity": assert_owned(private),
            "hashes": hashes,
            "protocol_sha256": digest(CONFIG),
            "templates": template_hashes(private),
            "utc": utc(),
        }
        write(private / "comparison-baseline.json", marker)
        write(
            output / "comparison-prepared.json",
            {
                "complete": True,
                "baseline_hashes": hashes,
                "protocol_sha256": digest(CONFIG),
                "load_executed": False,
            },
        )
    finally:
        env.command(["docker", "stop", "--timeout", "30", CLUSTER + "-control-plane"], timeout=60)


def one(private, output, condition):
    if snapshot()["host_available_bytes"] < 5 * 2**30:
        raise RuntimeError("PREFLIGHT_MEMORY_BELOW_5_GIB")
    with cal.exclusive(private):
        cal._execute(
            private,
            output,
            extension=Trial(condition),
            controlled_host=True,
            reuse_terminal_reads=True,
            peak_rate=16,
            http_concurrency=32,
            plateau_seconds=60,
        )


def run(private, output, mode):
    require_context()
    config()
    if env.command(["git", "status", "--porcelain"]).strip():
        raise RuntimeError("DIRTY_CHECKOUT")
    if mode == "prepare":
        prepare(private, output)
        return
    if output.exists():
        raise RuntimeError("OUTPUT_EXISTS")
    output.mkdir(parents=True)
    write(
        output / "protocol.json",
        {
            "config": config(),
            "protocol_sha256": digest(CONFIG),
            "infra_sha": env.command(["git", "rev-parse", "HEAD"]).strip(),
            "order": order(config()["seed"]),
            "mode": mode,
        },
    )
    if mode == "qualify":
        one(private, output / "qualification-fixed-1", "fixed-1")
        result = json.loads((output / "qualification-fixed-1/comparison-result.json").read_text())
        if (
            not result["execution_valid"]
            or result["accepted"] != 1020
            or result["max_active_requests"] > 28
        ):
            raise RuntimeError("QUALIFICATION_FAILED_OR_INSUFFICIENT_CLIENT_MARGIN")
        write(
            private / "comparison-qualified.json",
            {
                "infra_sha": env.command(["git", "rev-parse", "HEAD"]).strip(),
                "protocol_sha256": digest(CONFIG),
                "result_sha256": digest(output / "qualification-fixed-1/comparison-result.json"),
                "source": str(output.resolve()),
            },
        )
        return
    q = json.loads((private / "comparison-qualified.json").read_text())
    if (
        q["protocol_sha256"] != digest(CONFIG)
        or q["infra_sha"] != env.command(["git", "rev-parse", "HEAD"]).strip()
    ):
        raise RuntimeError("QUALIFICATION_REFERENCE_CHANGED")
    source = Path(q["source"]) / "qualification-fixed-1/comparison-result.json"
    if digest(source) != q["result_sha256"]:
        raise RuntimeError("QUALIFICATION_HASH")
    results = []
    campaign_started = time.monotonic()
    for block, conditions in enumerate(order(config()["seed"]), 1):
        block_start = time.monotonic()
        for position, condition in enumerate(conditions, 1):
            if (
                time.monotonic() - campaign_started > 160 * 60
                or time.monotonic() - block_start > 40 * 60
            ):
                raise RuntimeError("BLOCK_WINDOW_EXHAUSTED")
            folder = output / f"b{block}-p{position}-{condition}"
            print(f"Block {block}/3, position {position}/3: {condition}", flush=True)
            one(private, folder, condition)
            results.append(json.loads((folder / "comparison-result.json").read_text()))
            write(
                output / f"progress-{len(results):02d}.json",
                {"attempts_completed": len(results), "results": results},
            )
    write(
        output / "comparison-summary.json",
        {
            "complete": True,
            "results": results,
            "by_condition": {
                c: {
                    "attempts": 3,
                    "on_time_fractions": [
                        r["confirmed_in_time_fraction"] for r in results if r["condition"] == c
                    ],
                    "existing_pod_seconds": [
                        r["pod_time"]["existing_pod_seconds"]
                        for r in results
                        if r["condition"] == c
                    ],
                }
                for c in CONDITIONS
            },
            "limits": "three independent attempts per condition; descriptive blocked comparison, no power or population inference",
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("prepare", "qualify", "execute"), required=True)
    args = parser.parse_args()
    try:
        private, output = args.private.resolve(), args.output.resolve()
        if (
            private.is_relative_to(output)
            or output.is_relative_to(private)
            or private.is_relative_to(ROOT)
        ):
            raise RuntimeError("PRIVATE_PATH_OVERLAP")
        run(private, output, args.mode)
        print(json.dumps({"complete": True, "mode": args.mode, "output": str(output)}))
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": type(error).__name__,
                    "code": str(error) if isinstance(error, RuntimeError) else "COMPARISON_FAILED",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
