"""A2: bounded Kind recovery; explicit and automatic activation share one observer."""

from __future__ import annotations

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

from scripts import a1, a1_flow
from scripts.a1_runtime import (
    TARGET,
    Config,
    Runtime,
    candidate_crashed,
    check,
    digest,
    environment_lock,
    validate_template,
    write_json,
)
from scripts.verify_flow import Failure, SafeParser


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Journal:
    """Exclusive, fsynced records; incomplete or altered chains fail closed."""

    def __init__(self, root: Path, *, clock=time.monotonic):
        self.path = root / "journal"
        self.path.mkdir(exist_ok=True)
        self.clock, self.started = clock, clock()
        self.process = str(uuid4())
        self.records = []
        previous = None
        for index, path in enumerate(sorted(self.path.glob("*.json"))):
            record = read(path)
            check(path.name == f"{index:04d}.json", "JOURNAL_SEQUENCE_INVALID")
            check(record["previous"] == previous, "JOURNAL_CHAIN_INVALID")
            previous = digest(record)
            self.records.append(record)

    def emit(self, phase: str, **fields) -> None:
        record = {
            "phase": phase,
            "process_id": self.process,
            "elapsed_seconds": self.clock() - self.started,
            "utc": datetime.now(UTC).isoformat(),
            "previous": digest(self.records[-1]) if self.records else None,
            **fields,
        }
        write_json(self.path / f"{len(self.records):04d}.json", record)
        self.records.append(record)

    def phases(self, phase: str) -> list[dict]:
        return [r for r in self.records if r["phase"] == phase]


class ObservedRuntime(Runtime):
    def __init__(self, config: Config, journal: Journal):
        super().__init__(config)
        self.journal = journal
        self.mutation = "candidate"

    def patch_template(self, deployment: dict, template: dict, destination: Path) -> None:
        self.journal.emit(self.mutation + "_send_intent", template_hash=digest(template))
        super().patch_template(deployment, template, destination)
        self.journal.emit(self.mutation + "_sent", template_hash=digest(template))


def references(runtime: Runtime) -> list[str]:
    # Query metadata only: never retrieve/export values or hashes of secrets.
    projection = (
        '{range .items[*]}{.kind}{"/"}{.metadata.name}{"/"}{.metadata.uid}'
        '{"/"}{.metadata.resourceVersion}{"\\n"}{end}'
    )
    return sorted(
        runtime.kubectl("get", "secrets,configmaps", "-o", "jsonpath=" + projection).splitlines()
    )


def eligible(source: Path, config: Config) -> bool:
    result = read(source / "attempt-result.json")
    if result.get("deployment_verdict") != "rejected" or result.get("functional_stage") != (
        "not_executed_candidate_failed_startup"
    ):
        return False
    candidate = read(source / "candidate.json")
    diagnostic = read(source / "configuration-error.json")
    restore = read(source / "restore.json")
    return (
        result.get("deployment_verdict") == "rejected"
        and result.get("functional_stage") == "not_executed_candidate_failed_startup"
        and result.get("accepted_events") == 0
        and candidate.get("attempt") == result.get("attempt_id")
        and candidate.get("deployment_uid") == restore["deployment_uid"]
        and candidate.get("template_hash") == digest(restore["candidate_template"])
        and candidate_crashed(candidate, config)
        and diagnostic.get("db_pool_validation_observed") is True
        and diagnostic.get("pod_uid") == candidate["pods"][0]["uid"]
    )


def validate_source(runtime: Runtime, source: Path) -> tuple[dict, dict]:
    data = read(source / "restore.json")
    identity = read(source / "identity.json")
    check(identity["environment"] == runtime.config.identity(), "RESTORE_ENVIRONMENT_MISMATCH")
    check(data["identity"] == runtime.config.identity(), "RESTORE_ENVIRONMENT_MISMATCH")
    check(data["scenario"] in {"healthy", "invalid-pool"}, "RESTORE_SCENARIO_INVALID")
    for template in (data["healthy_template"], data["candidate_template"]):
        validate_template(template, runtime.config)
    check(
        a1.revision(data["healthy_template"], data["attempt_id"], data["scenario"])
        == data["candidate_template"],
        "RESTORE_DIFF_INVALID",
    )
    check(references(runtime) == read(source / "references.json")["metadata"], "REFERENCE_CHANGED")
    a1.other_workloads_unchanged(data["inventory"], runtime.inventory())
    deployment = runtime.get("deployment/" + TARGET)
    check(deployment["metadata"]["uid"] == data["deployment_uid"], "RESTORE_DEPLOYMENT_CHANGED")
    check(deployment["spec"]["replicas"] == 1, "RESTORE_REPLICAS_CHANGED")
    check(
        deployment["spec"]["template"] in (data["healthy_template"], data["candidate_template"]),
        "RESTORE_CANDIDATE_CHANGED",
    )
    return data, deployment


def observe_recovery(runtime: ObservedRuntime, source: Path, secret: str) -> dict:
    journal = runtime.journal
    started = journal.phases("recovery_flow_started")
    if started:
        # A previous HTTP exchange might have committed. Never send a replacement event.
        folder = source / started[-1]["directory"]
        check(
            folder.parent == source and folder.name.startswith("recovery-flow-"),
            "FLOW_PATH_INVALID",
        )
        check((folder / "result.json").is_file(), "RECOVERY_FLOW_INCOMPLETE_NO_REOFFER")
        old = read(folder / "result.json")
        check(
            old.get("acceptance_verified") and old.get("checkpoint"), "RECOVERY_ACCEPTANCE_UNKNOWN"
        )
        return a1_flow.verify(
            runtime,
            source / ("recovery-read-" + str(uuid4())),
            secret,
            checkpoint=old["checkpoint"],
        )
    folder = "recovery-flow-" + str(uuid4())
    journal.emit("recovery_flow_started", directory=folder)
    return a1_flow.verify(runtime, source / folder, secret)


def recover(runtime: ObservedRuntime, source: Path, output: Path, secret: str) -> dict:
    data, deployment = validate_source(runtime, source)
    journal = runtime.journal
    sent = journal.phases("restore_send_intent")
    check(len(sent) <= 1, "MULTIPLE_RESTORE_INTENTS")
    if deployment["spec"]["template"] == data["candidate_template"]:
        # An old request might still be in flight. Reading the candidate isn't proof it failed.
        check(not sent, "RESTORE_OUTCOME_UNRESOLVED_NO_RETRY")
        runtime.mutation = "restore"
        runtime.patch_template(deployment, data["healthy_template"], output / "restore-patch.json")
    else:
        check(
            bool(sent) or not journal.phases("candidate_send_intent"), "UNEXPECTED_HEALTHY_TEMPLATE"
        )
        journal.emit("healthy_template_reconciled", prior_restore_intent=bool(sent))
    record = runtime.wait_target(digest(data["healthy_template"]))
    write_json(output / "restored.json", record)
    journal.emit("healthy_converged")
    previous = {"state": "no_event_offered_by_attempt"}
    original = source / "flow" / "result.json"
    if original.is_file():
        old = read(original)
        check(old.get("acceptance_verified") and old.get("checkpoint"), "PRIOR_ACCEPTANCE_UNKNOWN")
        previous = a1_flow.verify(
            runtime, output / "previous-flow", secret, checkpoint=old["checkpoint"]
        )
    else:
        check(not (source / "flow").exists(), "PRIOR_FLOW_INCOMPLETE")
    fresh = observe_recovery(runtime, source, secret)
    a1.stable_pod(record, runtime.snapshot())
    a1.other_workloads_unchanged(data["inventory"], runtime.inventory())
    check(references(runtime) == read(source / "references.json")["metadata"], "REFERENCE_CHANGED")
    passed = fresh["success"] and previous.get("verdict", "approved") == "approved"
    journal.emit("recovery_observed", success=passed)
    return {
        "restored_configuration": True,
        "previous_event": previous,
        "fresh_event": fresh,
        "recovery_passed": passed,
        "scenario_passed": passed,
    }


def request(source: Path, config: Config, actor: str) -> dict:
    check(actor in {"human", "agent", "script"}, "ACTOR_REQUIRED")
    identity = read(source / "identity.json")
    check(identity["environment"] == config.identity(), "REQUEST_ENVIRONMENT_MISMATCH")
    check(identity["condition"] == "explicit", "EXPLICIT_CONDITION_REQUIRED")
    waiting = read(source / "awaiting-request.json")
    check(not (source / "result.json").exists(), "OBSERVER_ALREADY_ENDED")
    body = {
        "attempt_id": waiting["attempt_id"],
        "actor": actor,
        "utc": datetime.now(UTC).isoformat(),
    }
    temporary = source / ("request-" + str(uuid4()) + ".tmp")
    write_json(temporary, body)
    try:
        # Atomic publication without overwrite; observer never reads a partial request.
        os.link(temporary, source / "restore-request.json")
    finally:
        temporary.unlink()
    return {"scenario_passed": True, "request_recorded": True, "actor": actor}


def run(runtime: ObservedRuntime, output: Path, condition: str, scenario: str, secret: str) -> dict:
    journal = runtime.journal
    write_json(output / "references.json", {"metadata": references(runtime)})
    result = a1.attempt(runtime, output, scenario, secret)
    write_json(output / "attempt-result.json", result)
    journal.emit("candidate_decided", verdict=result["deployment_verdict"])
    if result["deployment_verdict"] == "approved":
        journal.emit("no_automatic_restore")
        return {**result, "policy_action": "none", "automatic_restore": False}
    check(eligible(output, runtime.config), "NO_DEFINITIVE_STARTUP_FAILURE")
    if condition == "explicit":
        write_json(output / "awaiting-request.json", {"attempt_id": result["attempt_id"]})
        journal.emit("awaiting_explicit_request")
        while not (output / "restore-request.json").exists():
            runtime.sleep(min(runtime.config.poll_seconds, runtime.remaining()))
        body = read(output / "restore-request.json")
        check(body["attempt_id"] == result["attempt_id"], "REQUEST_ATTEMPT_MISMATCH")
        check(body["actor"] in {"human", "agent", "script"}, "ACTOR_REQUIRED")
        actor = body["actor"]
    else:
        actor = "policy"
    journal.emit("restoration_requested", actor=actor)
    recovery = recover(runtime, output, output, secret)
    return {
        **result,
        "restoration": "verified" if recovery["recovery_passed"] else "failed",
        "policy_action": "restore" if condition == "auto" else "explicit_restore",
        "automatic_restore": condition == "auto",
        "recovery": recovery,
        "scenario_passed": result["scenario_passed"] and recovery["recovery_passed"],
    }


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("run", "request", "recover"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--condition", choices=("explicit", "auto"))
    parser.add_argument("--scenario", choices=("healthy", "invalid-pool"))
    parser.add_argument("--actor", choices=("human", "agent", "script"))
    args = parser.parse_args(argv)
    output = None
    try:
        check(sys.version_info[:2] == (3, 12), "PYTHON_VERSION_MISMATCH")
        config = Config.load(args.config)
        check(
            args.mode != "run" or bool(args.condition and args.scenario), "RUN_ARGUMENTS_REQUIRED"
        )
        check(args.mode == "run" or args.source is not None, "SOURCE_REQUIRED")
        secret = os.environ.get("CARRIER_ALPHA_WEBHOOK_SECRET", "")
        check(args.mode == "request" or bool(secret), "MISSING_CARRIER_SECRET")
        args.output.mkdir(exist_ok=False)
        output = args.output.resolve()
        source = args.source.resolve() if args.source else output
        if args.mode == "request":
            result = request(source, config, args.actor)
        else:
            with environment_lock(config):
                if args.mode == "run":
                    write_json(
                        output / "identity.json",
                        {
                            **a1.provenance(),
                            "environment": config.identity(),
                            "condition": args.condition,
                            "scenario": args.scenario,
                            "limits": {
                                "operation": config.operation_seconds,
                                "rollout": config.rollout_seconds,
                                "flow": config.flow_seconds,
                                "poll": config.poll_seconds,
                            },
                        },
                    )
                else:
                    check((source / "identity.json").is_file(), "SOURCE_IDENTITY_REQUIRED")
                    write_json(
                        output / "identity.json",
                        {
                            **a1.provenance(),
                            "environment": config.identity(),
                            "mode": "recover",
                            "source_attempt": read(source / "restore.json")["attempt_id"],
                        },
                    )
                journal = Journal(source)
                runtime = ObservedRuntime(config, journal)
                runtime.preflight()
                journal.emit("operation_started", mode=args.mode)
                if args.mode == "run":
                    result = run(runtime, output, args.condition, args.scenario, secret)
                else:
                    journal.emit("restoration_requested", actor=args.actor or "agent", resumed=True)
                    result = recover(runtime, source, output, secret)
                    result["separate_recovery_operation"] = True
                journal.emit("operation_finished", success=result["scenario_passed"])
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
        message, code = (
            (error.code, error.exit_code)
            if isinstance(error, Failure)
            else (
                "INTERRUPTED_OUTCOME_UNKNOWN"
                if isinstance(error, KeyboardInterrupt)
                else "OPERATION_OR_EVIDENCE_INVALID",
                130 if isinstance(error, KeyboardInterrupt) else 2,
            )
        )
        result = {"scenario_passed": False, "error": message, "automatic_retry": False}
    try:
        if output is not None:
            write_json(output / "result.json", result)
    except OSError:
        result["evidence_write_failed"] = True
        code = 2
    print(json.dumps(result, sort_keys=True), file=sys.stdout if code == 0 else sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
