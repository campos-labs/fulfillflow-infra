"""A1: explicit local lifecycle, one-workload attempt, and separate restoration."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import a1_flow
from scripts.a1_runtime import (
    MARKER,
    ROOT,
    TARGET,
    WORKLOADS,
    Config,
    Runtime,
    candidate_crashed,
    check,
    converged,
    digest,
    environment_lock,
    validate_template,
    write_json,
)
from scripts.verify_flow import EXPECTED_APPLICATION_SHA, Failure, SafeParser

DIAGNOSTIC_SECONDS = 5


def configuration_diagnostic(runtime: Runtime, record: dict, output: Path) -> bool:
    """A terminated pod can be observable before its log is available."""
    pod = record["pods"][0]
    observations = []
    previous_deadline = runtime.deadline
    started = runtime.clock()
    runtime.deadline = min(previous_deadline, started + DIAGNOSTIC_SECONDS)

    def same_identity():
        current = runtime.snapshot()
        check(
            current["deployment_uid"] == record["deployment_uid"]
            and current["template_hash"] == record["template_hash"]
            and len(current["pods"]) == 1
            and current["pods"][0]["uid"] == pod["uid"]
            and not current["pods"][0]["deleting"]
            and current["pods"][0]["containers"][0]["image_id"] == runtime.config.image_id,
            "DIAGNOSTIC_IDENTITY_CHANGED",
        )

    try:
        while runtime.clock() < runtime.deadline:
            same_identity()
            logs = runtime.kubectl("logs", pod["name"], "--tail=80", "--limit-bytes=12000")
            same_identity()
            confirmed = "db_pool_size" in logs and "greater than or equal to 1" in logs
            observations.append(
                {
                    "elapsed_seconds": runtime.clock() - started,
                    "empty": not logs.strip(),
                    "text_hash": digest(logs),
                    "characters": len(logs),
                    "db_pool_validation_observed": confirmed,
                }
            )
            if logs.strip():
                return confirmed  # An unrelated nonempty error never authorizes restoration.
            remaining = runtime.deadline - runtime.clock()
            if remaining > 0:
                runtime.sleep(min(runtime.config.poll_seconds, remaining))
        return False
    finally:
        runtime.deadline = previous_deadline
        write_json(
            output / "diagnostic-observations.json",
            {
                "pod_uid": pod["uid"],
                "maximum_seconds": DIAGNOSTIC_SECONDS,
                "samples": observations,
                "raw_log_exported": False,
            },
        )


def revision(template: dict, attempt: str, scenario: str) -> dict:
    candidate = copy.deepcopy(template)
    candidate["metadata"].setdefault("annotations", {})[MARKER] = attempt
    if scenario == "invalid-pool":
        env = candidate["spec"]["containers"][0]["env"]
        setting = next(e for e in env if e["name"] == "DB_POOL_SIZE")
        check(setting == {"name": "DB_POOL_SIZE", "value": "3"}, "UNEXPECTED_HEALTHY_POOL")
        setting["value"] = "0"
    return candidate


def other_workloads_unchanged(before: dict, after: dict) -> None:
    check(
        {k: v for k, v in before.items() if k != TARGET}
        == {k: v for k, v in after.items() if k != TARGET},
        "OTHER_WORKLOAD_CHANGED",
    )


def stable_pod(before: dict, after: dict) -> None:
    check(
        before["deployment_uid"] == after["deployment_uid"]
        and before["template_hash"] == after["template_hash"]
        and before["pods"] == after["pods"],
        "CANDIDATE_EXECUTION_CHANGED",
    )


def attempt(
    runtime: Runtime, output: Path, scenario: str, secret: str, *, flow_verifier=None
) -> dict:
    before = runtime.inventory()
    check(all(v["replicas"] == 1 for v in before.values()), "RUNTIME_NOT_STARTED")
    deployment = runtime.get("deployment/" + TARGET)
    template = deployment["spec"]["template"]
    start = runtime.snapshot()
    check(converged(start, runtime.config), "HEALTHY_TARGET_REQUIRED")
    attempt_id = str(uuid4())
    candidate = revision(template, attempt_id, scenario)
    validate_template(candidate, runtime.config)
    restore = {
        "identity": runtime.config.identity(),
        "deployment_uid": deployment["metadata"]["uid"],
        "healthy_template": template,
        "candidate_template": candidate,
        "inventory": before,
        "scenario": scenario,
        "attempt_id": attempt_id,
    }
    # Persist restoration information before any mutation. It contains references, never secrets.
    write_json(output / "restore.json", restore)
    write_json(output / "before.json", start)
    runtime.patch_template(deployment, candidate, output / "candidate-patch.json")
    record = runtime.wait_target(digest(candidate), allow_fault=scenario == "invalid-pool")
    write_json(output / "candidate.json", record)
    check(all(p["attempt"] == attempt_id for p in record["pods"]), "CANDIDATE_NOT_EXERCISED")
    if scenario == "invalid-pool":
        check(candidate_crashed(record, runtime.config), "EXPECTED_STARTUP_FAILURE_NOT_OBSERVED")
        confirmed = configuration_diagnostic(runtime, record, output)
        write_json(
            output / "configuration-error.json",
            {
                "db_pool_validation_observed": confirmed,
                "source": "candidate pod log; text withheld",
                "pod_uid": record["pods"][0]["uid"],
            },
        )
        check(confirmed, "EXPECTED_CONFIGURATION_DIAGNOSTIC_MISSING")
        result = {
            "deployment_verdict": "rejected",
            "scenario_passed": True,
            "functional_stage": "not_executed_candidate_failed_startup",
            "accepted_events": 0,
            "additional_functional_information": "not_demonstrated",
        }
    else:
        result = (flow_verifier or a1_flow.verify)(runtime, output / "flow", secret)
        after = runtime.snapshot()
        stable_pod(record, after)
        result = {
            "deployment_verdict": result["verdict"],
            "scenario_passed": result["success"],
            "functional": result,
            "functional_stage": "executed",
        }
    other_workloads_unchanged(before, runtime.inventory())
    return {
        "scenario": scenario,
        "attempt_id": attempt_id,
        "restoration": "requires_explicit_restore_command",
        **result,
    }


def restore(runtime: Runtime, output: Path, source: Path, secret: str) -> dict:
    data = json.loads((source / "restore.json").read_text(encoding="utf-8"))
    check(data["identity"] == runtime.config.identity(), "RESTORE_ENVIRONMENT_MISMATCH")
    deployment = runtime.get("deployment/" + TARGET)
    check(deployment["metadata"]["uid"] == data["deployment_uid"], "RESTORE_DEPLOYMENT_CHANGED")
    check(deployment["spec"]["template"] == data["candidate_template"], "RESTORE_CANDIDATE_CHANGED")
    check(data["scenario"] in {"healthy", "invalid-pool"}, "RESTORE_SCENARIO_INVALID")
    check(
        revision(data["healthy_template"], data["attempt_id"], data["scenario"])
        == data["candidate_template"],
        "RESTORE_DIFF_INVALID",
    )
    other_workloads_unchanged(data["inventory"], runtime.inventory())
    runtime.patch_template(deployment, data["healthy_template"], output / "restore-patch.json")
    record = runtime.wait_target(digest(data["healthy_template"]))
    write_json(output / "restored.json", record)
    source_flow = source / "flow/result.json"
    previous = {"state": "no_event_offered_by_attempt"}
    if source_flow.exists():
        old = json.loads(source_flow.read_text(encoding="utf-8"))
        if old.get("acceptance_verified"):
            previous = a1_flow.verify(
                runtime, output / "previous-flow", secret, checkpoint=old["checkpoint"]
            )
        elif old.get("webhook_offered"):
            previous = {"state": "acceptance_unknown_no_safe_lookup", "verdict": "inconclusive"}
    elif (source / "flow").exists():
        previous = {"state": "flow_record_incomplete", "verdict": "inconclusive"}
    fresh = a1_flow.verify(runtime, output / "fresh-flow", secret)
    stable_pod(record, runtime.snapshot())
    other_workloads_unchanged(data["inventory"], runtime.inventory())
    return {
        "restored_configuration": True,
        "source_attempt": data["attempt_id"],
        "previous_event": previous,
        "fresh_event": fresh,
        "scenario_passed": fresh["success"] and previous.get("verdict", "approved") == "approved",
    }


def lifecycle(runtime: Runtime, output: Path, mode: str) -> dict:
    c = runtime.config
    runtime.inventory()
    stateful = runtime.get("statefulsets")["items"]
    check(
        {x["metadata"]["name"] for x in stateful} == {"postgres", "rabbitmq"},
        "STATEFUL_SET_MISMATCH",
    )
    for item in stateful:
        check(
            item["metadata"].get("labels", {}).get("app.kubernetes.io/part-of") == "fulfillflow",
            "STATEFUL_OWNER_MISMATCH",
        )
    if mode == "resume":
        jobs = {j["metadata"]["name"]: j for j in runtime.get("jobs")["items"]}
        check(
            all(
                jobs.get("migrate-" + owner, {}).get("status", {}).get("succeeded") == 1
                for owner in ("core", "tracking", "notifications")
            ),
            "MIGRATIONS_NOT_COMPLETED",
        )
    count = "1" if mode == "resume" else "0"
    resources = ["statefulset/postgres", "statefulset/rabbitmq"] + [
        "deployment/" + x for x in WORKLOADS
    ]
    if mode == "pause":
        resources.reverse()
    for resource in resources:
        item = runtime.get(resource)
        check(item["spec"]["replicas"] in (0, 1), "UNEXPECTED_REPLICA_COUNT")
        if item["spec"]["replicas"] != int(count):
            runtime.kubectl(
                "scale",
                resource,
                "--current-replicas=" + str(item["spec"]["replicas"]),
                "--replicas=" + count,
            )
        if mode == "resume":
            runtime.command(
                runtime.prefix()
                + ["rollout", "status", resource, "--timeout=" + str(int(c.rollout_seconds)) + "s"],
                timeout=c.rollout_seconds + 5,
            )
    if mode == "pause":
        end = min(runtime.deadline, runtime.clock() + 60)
        while any(
            p.get("status", {}).get("phase") not in ("Succeeded", "Failed")
            for p in runtime.get("pods")["items"]
        ):
            check(runtime.clock() < end, "PODS_NOT_STOPPED")
            runtime.sleep(1)
        write_json(output / "paused-inventory.json", runtime.inventory())
        runtime.command([c.docker, "stop", "--timeout", "30", c.node], timeout=45)
    return {"mode": mode, "scenario_passed": True, "replicas": int(count), "data_preserved": True}


def provenance() -> dict:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=10
    )
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=10,
    )
    check(revision.returncode == dirty.returncode == 0, "GIT_IDENTITY_UNAVAILABLE")
    return {
        "infra_sha": revision.stdout.strip(),
        "working_tree_dirty": bool(dirty.stdout.strip()),
        "application_sha": EXPECTED_APPLICATION_SHA,
        "script_hashes": {
            p.name: digest(p.read_text(encoding="utf-8")) for p in (ROOT / "scripts").glob("*.py")
        },
    }


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--mode", required=True, choices=("status", "resume", "attempt", "restore", "pause")
    )
    parser.add_argument("--scenario", choices=("healthy", "invalid-pool"))
    parser.add_argument("--source", type=Path)
    args = parser.parse_args(argv)
    output = None
    started = time.monotonic()
    result = {}
    runtime = None
    try:
        check(sys.version_info[:2] == (3, 12), "PYTHON_VERSION_MISMATCH")
        c = Config.load(args.config)
        secret = os.environ.get("CARRIER_ALPHA_WEBHOOK_SECRET", "")
        check(args.mode != "attempt" or args.scenario is not None, "SCENARIO_REQUIRED")
        check(args.mode != "restore" or args.source is not None, "SOURCE_REQUIRED")
        check(args.mode not in {"attempt", "restore"} or bool(secret), "MISSING_CARRIER_SECRET")
        args.output.mkdir(exist_ok=False)
        output = args.output
        write_json(
            output / "identity.json",
            {
                **c.identity(),
                **provenance(),
                "mode": args.mode,
                "started_at": datetime.now(UTC).isoformat(),
                "limits": {
                    "operation": c.operation_seconds,
                    "rollout": c.rollout_seconds,
                    "flow": c.flow_seconds,
                    "poll": c.poll_seconds,
                },
            },
        )
        with environment_lock(c):
            runtime = Runtime(c)
            if args.mode == "resume":
                # Starts only the already existing dedicated container; no cluster/bootstrap creation.
                info = json.loads(runtime.command([c.docker, "inspect", c.node]))[0]
                check(
                    info["Config"].get("Labels", {}).get("io.x-k8s.kind.cluster") == c.context[5:],
                    "DOCKER_NODE_MISMATCH",
                )
                if not info["State"]["Running"]:
                    runtime.command([c.docker, "start", c.node], timeout=45)
                end = min(runtime.deadline, runtime.clock() + 60)
                while True:
                    try:
                        runtime.kubectl("get", "--raw=/readyz")
                        break
                    except Failure as error:
                        if runtime.clock() >= end:
                            raise Failure("LOCAL_API_UNAVAILABLE", 3) from error
                        runtime.sleep(2)
            runtime.preflight()
            if args.mode in {"resume", "pause"}:
                result = lifecycle(runtime, output, args.mode)
            elif args.mode == "attempt":
                result = attempt(runtime, output, args.scenario, secret)
            elif args.mode == "restore":
                result = restore(runtime, output, args.source, secret)
            else:
                result = {"inventory": runtime.inventory(), "scenario_passed": True}
        result["elapsed_seconds"] = time.monotonic() - started
        code = 0 if result["scenario_passed"] else 6
    except (
        Failure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        IndexError,
        StopIteration,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        if isinstance(error, Failure):
            message, code = error.code, error.exit_code
        elif isinstance(error, KeyboardInterrupt):
            message, code = "INTERRUPTED_OUTCOME_UNKNOWN", 130
        else:
            message, code = "OPERATION_OR_EVIDENCE_INVALID", 2
        result = {
            "scenario_passed": False,
            "error": message,
            "mutation_outcome": "inspect_evidence_no_auto_retry",
            "elapsed_seconds": time.monotonic() - started,
        }
    try:
        if output is not None:
            if code and runtime is not None and runtime.last_snapshot is not None:
                write_json(output / "failure-snapshot.json", runtime.last_snapshot)
            write_json(output / "result.json", result)
    except OSError:
        result["evidence_write_failed"] = True
        code = 2
    print(json.dumps(result, sort_keys=True), file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
