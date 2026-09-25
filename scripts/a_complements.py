"""Bounded A complements: pending work and fail-closed observation, separate from A2."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import a1, a1_flow, a2
from scripts import a2_campaign as campaign
from scripts import verify_flow as flow
from scripts.a1_runtime import (
    TARGET,
    Config,
    Runtime,
    check,
    converged,
    digest,
    environment_lock,
    write_json,
)

WINDOW = 2700
ERRORS = (
    flow.Failure,
    OSError,
    ValueError,
    KeyError,
    TypeError,
    subprocess.SubprocessError,
    KeyboardInterrupt,
)


def order(pilot: bool) -> list[dict]:
    conditions = (
        [("explicit", "auto")]
        if pilot
        else [("explicit", "auto"), ("auto", "explicit"), ("explicit", "auto")]
    )
    cases = [
        {"scenario": "pending", "pair": pair, "condition": condition}
        for pair, members in enumerate(conditions, 1)
        for condition in members
    ]
    cases += [
        {"scenario": "inconclusive", "pair": n, "condition": "auto"}
        for n in range(1, 2 if pilot else 4)
    ]
    return [{"number": n, **case} for n, case in enumerate(cases, 1)]


def pending_record(record: dict, event: str) -> bool:
    flow.require(record.get("tracking_event_id") == event and record.get("required") is True)
    flow.require(record.get("publication") in {"PENDING", "LEASED", "SENT"})
    flow.require(record.get("processing") == "NOT_RECEIVED", "WORK_ALREADY_RECEIVED")
    flow.require(record.get("status") is None and record.get("notification_id") is None)
    return record["publication"] == "SENT"


def prepare_pending(runtime: Runtime, output: Path, secret: str) -> dict:
    """Persist a resumable checkpoint even when preparation fails; never retry admission."""
    destination = output / "flow"
    with a1_flow.tunnel(runtime) as (url, identity):
        config = flow.Config(
            url,
            destination,
            secret=secret,
            deadline_seconds=runtime.config.flow_seconds,
            poll_seconds=runtime.config.poll_seconds,
        )
        observations = a1_flow.Observations(destination)
        verifier = a1_flow.ObservedVerifier(config, observations, flow.HttpTransport())
        try:
            observations.emit("started", run_id=verifier.run_id, event_id=verifier.event_id)
            order_id, shipment, tracking_code = verifier.prepare()
            raw, headers = verifier.webhook(tracking_code)
            inbox, location = verifier.admit(raw, headers)
            event = verifier.tracking(inbox, location, shipment)
            verifier.final_business(order_id, shipment)
            while True:
                record = verifier.get(f"/api/v1/notification-status/{event}")
                if pending_record(record, event):
                    break
                verifier.pause()
            observations.emit("pending_before_authorization", tracking_event_id=event)
            result = {
                **verifier.summary(False),
                "verdict": "pending",
                "checkpoint": observations.checkpoint,
                "observation_only": False,
                "pending_stage": "published_not_received",
                "notification_projection": a1_flow.projection(record),
            }
            write_json(destination / "result.json", result)
            write_json(destination / "core-identity.json", identity)
            return result
        finally:
            observations.close()
            # A lost response must remain distinguishable from known durable acceptance.
            if not (destination / "result.json").exists():
                write_json(
                    destination / "result.json",
                    {
                        **verifier.summary(False, "PREPARATION_FAILED"),
                        "verdict": "inconclusive",
                        "checkpoint": observations.checkpoint,
                    },
                )


class TimedReads:
    def __init__(self, origin: float, event: str):
        self.origin, self.event = origin, event
        self.transport = flow.HttpTransport()
        self.first = threading.Event()
        self.records = []
        self.simulated_at = None

    def __call__(self, method, url, headers, body, timeout):
        check(method == "GET", "RESUMPTION_MUST_BE_READ_ONLY")
        begin = time.monotonic() - self.origin
        path = urlsplit(url).path
        response = self.transport(method, url, headers, body, timeout)
        end = time.monotonic() - self.origin
        self.records.append(
            {
                "path": path,
                "http_status": response.status,
                "begin_seconds": begin,
                "end_seconds": end,
                "utc": datetime.now(UTC).isoformat(),
            }
        )
        if path == f"/api/v1/notification-status/{self.event}" and response.status == 200:
            record = json.loads(response.body)
            if record.get("status") == "SIMULATED" and record.get("processing") == "DONE":
                if self.simulated_at is None:
                    self.simulated_at = end
        self.first.set()
        return response


class ParallelSignals:
    """Independent observers, common monotonic origin, no Kubernetes mutation."""

    def __init__(
        self,
        config: Config,
        folder: Path,
        checkpoint: dict,
        secret: str,
        origin: float,
        healthy_hash: str,
        deployment_uid: str,
    ):
        self.config, self.folder, self.checkpoint, self.secret = config, folder, checkpoint, secret
        self.origin, self.healthy_hash, self.deployment_uid = origin, healthy_hash, deployment_uid
        self.transport = TimedReads(origin, checkpoint["tracking_event_id"])
        self.first = threading.Event()
        self.stop = threading.Event()
        self.errors = []
        self.snapshots = []
        self.converged_at = None
        self.functional = None
        self.threads = []

    def target(self):
        runtime = Runtime(self.config)
        until = time.monotonic() + self.config.flow_seconds
        try:
            while not self.stop.is_set():
                begin = time.monotonic() - self.origin
                record = runtime.snapshot()
                check(
                    record["deployment_uid"] == self.deployment_uid, "OBSERVED_DEPLOYMENT_CHANGED"
                )
                end = time.monotonic() - self.origin
                self.snapshots.append(
                    {
                        "begin_seconds": begin,
                        "end_seconds": end,
                        "snapshot": record,
                    }
                )
                self.first.set()
                if record["template_hash"] == self.healthy_hash and converged(record, self.config):
                    self.converged_at = end
                    return
                check(time.monotonic() < until, "PARALLEL_READINESS_DEADLINE")
                self.stop.wait(self.config.poll_seconds)
        except ERRORS as error:
            self.errors.append(
                error.code if isinstance(error, flow.Failure) else "READINESS_FAILED"
            )
            self.first.set()

    def business(self):
        try:
            self.functional = a1_flow.verify(
                Runtime(self.config),
                self.folder / "parallel-flow",
                self.secret,
                checkpoint=self.checkpoint,
                transport=self.transport,
            )
        except ERRORS as error:
            self.errors.append(error.code if isinstance(error, flow.Failure) else "BUSINESS_FAILED")
        finally:
            self.transport.first.set()

    def start(self):
        for target in (self.target, self.business):
            thread = threading.Thread(target=target, daemon=True)
            self.threads.append(thread)
            thread.start()
        check(self.first.wait(30) and self.transport.first.wait(30), "OBSERVERS_NOT_STARTED")
        check(not self.errors, "OBSERVER_FAILED_BEFORE_AUTHORIZATION")
        check(self.functional is None, "FLOW_ENDED_BEFORE_AUTHORIZATION")

    def finish(self, *, abort=False):
        if abort:
            self.stop.set()
        for thread in self.threads:
            thread.join(self.config.flow_seconds + 20)
        self.stop.set()
        check(not any(t.is_alive() for t in self.threads), "OBSERVER_NOT_TERMINATED")
        result = {
            "converged_seconds": self.converged_at,
            "notification_observed_seconds": self.transport.simulated_at,
            "difference_seconds": (
                self.transport.simulated_at - self.converged_at
                if self.transport.simulated_at is not None and self.converged_at is not None
                else None
            ),
            "functional": self.functional,
            "errors": self.errors,
            "poll_seconds": self.config.poll_seconds,
            "snapshots": self.snapshots,
            "http_intervals": self.transport.records,
            "signal": "healthy_revision_convergence_not_exact_Ready_transition",
        }
        write_json(self.folder / "parallel-signals.json", result)
        if not abort:
            check(not self.errors and self.converged_at is not None, "PARALLEL_READINESS_FAILED")
            check(bool(self.functional and self.functional["success"]), "PARALLEL_BUSINESS_FAILED")
            check(self.transport.simulated_at is not None, "TERMINAL_SIGNAL_MISSING")
        return result


class QueryFault:
    """Single controlled observation failure; no server or worker is modified."""

    def __init__(self, transport=None):
        self.transport = transport or flow.HttpTransport()
        self.injected = 0

    def __call__(self, method, url, headers, body, timeout):
        if method == "GET" and urlsplit(url).path.startswith("/api/v1/notification-status/"):
            check(self.injected == 0, "UNEXPECTED_RETRY_AFTER_INJECTION")
            self.injected += 1
            return flow.Response(503, {}, b"{}")
        return self.transport(method, url, headers, body, timeout)


def mutation_identity(runtime: Runtime) -> dict:
    deployment = runtime.get("deployment/" + TARGET)
    return {
        "uid": deployment["metadata"]["uid"],
        "generation": deployment["metadata"]["generation"],
        "replicas": deployment["spec"]["replicas"],
        "template_hash": digest(deployment["spec"]["template"]),
        "inventory": runtime.inventory(),
        "references": a2.references(runtime),
    }


def assert_abstained(runtime: a2.ObservedRuntime, before: dict) -> dict:
    after = mutation_identity(runtime)
    check(before == after, "CONFIGURATION_CHANGED_DURING_ABSTENTION")
    check(not runtime.journal.phases("restore_send_intent"), "UNEXPECTED_RESTORE_INTENT")
    check(not runtime.journal.phases("restore_sent"), "UNEXPECTED_RESTORE_SENT")
    check(not runtime.journal.phases("restoration_requested"), "UNEXPECTED_RESTORE_REQUEST")
    return {"before": before, "after": after, "restore_intents": 0, "restore_sent": 0}


def one_attempt(
    config: Config, config_path: Path, folder: Path, case: dict, secret: str, provenance: dict
) -> dict:
    folder.mkdir()
    write_json(
        folder / "identity.json",
        {
            **provenance,
            "environment": config.identity(),
            **case,
            "underlying_scenario": "invalid-pool" if case["scenario"] == "pending" else "healthy",
        },
    )
    journal = a2.Journal(folder)
    runtime = a2.ObservedRuntime(config, journal)
    origin = journal.started
    stop, errors = threading.Event(), []
    helper = None
    observers = []
    preparation = {}

    def prepare(current, output, key):
        journal.emit("preparation_started")
        preparation.update(prepare_pending(current, output, key))
        data = a2.read(output / "restore.json")
        observer = ParallelSignals(
            config,
            folder,
            preparation["checkpoint"],
            key,
            origin,
            digest(data["healthy_template"]),
            data["deployment_uid"],
        )
        observers.append(observer)
        observer.start()
        journal.emit("preparation_finished", pending_stage=preparation["pending_stage"])

    before = {}
    injected = QueryFault()

    def uncertain(current, output, key):
        before.update(mutation_identity(current))
        return a1_flow.verify(current, output, key, transport=injected)

    try:
        runtime.preflight()
        journal.emit("operation_started", mode="complement")
        if case["scenario"] == "pending":
            if case["condition"] == "explicit":
                helper = threading.Thread(
                    target=campaign.explicit_command,
                    args=(config_path, folder, stop, errors),
                    daemon=True,
                )
                helper.start()
            result = a2.run(
                runtime,
                folder,
                case["condition"],
                "invalid-pool",
                secret,
                prepare_recovery=prepare,
            )
            check(not errors and result["scenario_passed"], "RECOVERY_NOT_VERIFIED")
            check(result["recovery"]["previous_event"]["success"], "PENDING_EVENT_NOT_RECOVERED")
            check(len(journal.phases("restore_send_intent")) == 1, "RESTORE_COUNT_MISMATCH")
            signals = observers[0].finish()
            observers.clear()
            requested = journal.phases("restoration_requested")[0]["elapsed_seconds"]
            authorized = journal.phases("policy_authorized")[0]["elapsed_seconds"]
            result.update(
                accepted_events=1,
                functional_stage="pending_prepared_after_startup_detection",
                accepted_pending_events=1,
                completed_pending_events=1,
                pending_stage=preparation["pending_stage"],
                converged_seconds=signals["converged_seconds"],
                notification_observed_seconds=signals["notification_observed_seconds"],
                signal_difference_seconds=signals["difference_seconds"],
                request_to_terminal_seconds=signals["notification_observed_seconds"] - requested,
                authorization_to_terminal_seconds=signals["notification_observed_seconds"]
                - authorized,
                signals={
                    k: v
                    for k, v in signals.items()
                    if k not in {"snapshots", "http_intervals", "functional"}
                },
                preparation_seconds=campaign.elapsed(
                    journal.records, "preparation_started", "preparation_finished"
                ),
                authorized_to_request_seconds=campaign.elapsed(
                    journal.records, "policy_authorized", "restoration_requested"
                ),
            )
        else:
            try:
                a2.run(runtime, folder, "auto", "healthy", secret, flow_verifier=uncertain)
            except flow.Failure as error:
                check(error.code == "NO_DEFINITIVE_STARTUP_FAILURE", "UNEXPECTED_POLICY_FAILURE")
            else:
                raise flow.Failure("EXPECTED_ABSTENTION_MISSING")
            original = a2.read(folder / "flow/result.json")
            check(
                injected.injected == 1
                and original["verdict"] == "inconclusive"
                and original["acceptance_verified"],
                "INJECTION_NOT_VERIFIED",
            )
            proof = assert_abstained(runtime, before)
            write_json(folder / "abstention-proof.json", proof)
            journal.emit("abstention_verified", injection="observer_transport_503")
            resumed = a1_flow.verify(
                runtime,
                folder / "resumed-read",
                secret,
                checkpoint=original["checkpoint"],
            )
            check(resumed["success"], "RESUMED_OBSERVATION_FAILED")
            assert_abstained(runtime, before)
            result = {
                "scenario_passed": True,
                "deployment_verdict": "inconclusive",
                "policy_action": "abstain",
                "automatic_restore": False,
                "accepted_pending_events": 0,
                "completed_pending_events": 0,
                "accepted_observed_events": 1,
                "completed_observed_events": 1,
                "injection": "observer_transport_503_not_real_service_outage",
                "resumed": resumed,
            }
        journal.emit("operation_finished", success=True)
        write_json(folder / "result.json", result)
        return result
    finally:
        stop.set()
        if helper:
            helper.join(35)
            check(not helper.is_alive(), "REQUEST_PROCESS_UNRESOLVED")
        for observer in observers:
            if not (folder / "parallel-signals.json").exists():
                observer.finish(abort=True)


def execute(
    config: Config,
    config_path: Path,
    output: Path,
    provenance: dict,
    secret: str,
    pilot: bool,
    pilot_reference: dict | None = None,
) -> dict:
    started, rows, error, touched, shutdown = time.monotonic(), [], None, False, None
    protocol = {
        "version": 1,
        "pilot_reference": pilot_reference,
        "stage": "pilot" if pilot else "evaluation",
        "order": order(pilot),
        "provenance": provenance,
        "environment": config.identity(),
        "limits": {"operation": 600, "flow": 90, "rollout": 90, "poll": 1, "window": WINDOW},
        "preparation": "confirmed_202_tracking_order_completed_SENT_NOT_RECEIVED",
        "authorization": "after_common_preparation_and_both_observers_started",
        "injection": "one_observer_transport_503_in_separate_healthy_attempt",
        "explicit_actor": "script_not_human",
    }
    write_json(output / "protocol.json", protocol)
    write_json(output / "protocol-hash.json", {"sha256_canonical_json": digest(protocol)})
    try:
        campaign.host_check(Runtime(config))
        touched = True
        (output / "resume").mkdir()
        campaign.prepare_runtime(config, output / "resume")
        baseline = campaign.health(Runtime(config))
        write_json(output / "baseline.json", baseline)
        power = campaign.power_identity()
        write_json(output / "power.json", power)
        for case in protocol["order"]:
            check(time.monotonic() - started + 900 < WINDOW, "WINDOW_RESERVE_REACHED")
            check(a1.provenance() == provenance, "SOURCE_CHANGED")
            campaign.host_check(Runtime(config))
            check(campaign.power_identity() == power, "POWER_CONFIGURATION_CHANGED")
            check(campaign.health(Runtime(config)) == baseline, "BASELINE_CHANGED")
            folder = output / f"{case['number']:02d}-{case['scenario']}-{case['condition']}"
            row = {**case, "usable": False, "scenario_passed": False}
            rows.append(row)
            print(
                f"A complement {case['number']}/{len(protocol['order'])}: "
                f"{case['scenario']} / {case['condition']}",
                flush=True,
            )
            result = one_attempt(config, config_path, folder, case, secret, provenance)
            row.update(result)
            if case["scenario"] == "inconclusive":
                campaign.cleanup(config, folder, secret)
            check(campaign.health(Runtime(config)) == baseline, "BASELINE_NOT_RESTORED")
            check(campaign.power_identity() == power, "POWER_CONFIGURATION_CHANGED")
            row["usable"] = True
            write_json(folder / "complement-row.json", row)
        write_json(output / "final-health.json", campaign.health(Runtime(config)))
    except ERRORS as caught:
        error = (
            caught.code if isinstance(caught, flow.Failure) else "INTERRUPTED_OR_OPERATION_FAILED"
        )
        if rows and not rows[-1]["usable"]:
            rows[-1]["error"] = error
    finally:
        if touched:
            try:
                pause = output / "pause"
                pause.mkdir()
                runtime = Runtime(config)
                runtime.preflight()
                shutdown = a1.lifecycle(runtime, pause, "pause")
                write_json(pause / "result.json", shutdown)
            except ERRORS:
                shutdown = {"scenario_passed": False, "error": "PAUSE_FAILED_INSPECT_LAB"}
    return {
        "complete": error is None
        and len(rows) == len(protocol["order"])
        and bool(shutdown and shutdown["scenario_passed"]),
        "error": error,
        "attempts": rows,
        "shutdown": shutdown,
        "elapsed_seconds": time.monotonic() - started,
        "limits": [
            "Separate from A2 series03; pilot is not evaluation",
            "One pending event per attempt; no sample inflation from smoke or duplicates",
            "Infrastructure restores configuration; application owns durable recovery",
            "Controlled client observation failure, not real Notifications API outage",
            "Parallel observed times include query intervals and polling",
            "No automatic retry/replacement; no human reaction or production reliability claim",
        ],
    }


def validate_pilot(source: Path | None, config: Config, provenance: dict) -> None:
    check(source is not None and source.is_dir(), "PILOT_EVIDENCE_REQUIRED")
    source = source.resolve()
    hashes = {}
    for line in (source / "checksums.sha256").read_text(encoding="utf-8").splitlines():
        expected, name = line.split("  ", 1)
        target = (source / name).resolve()
        check(target.is_relative_to(source), "INVALID_EVIDENCE_PATH")
        check(hashlib.sha256(target.read_bytes()).hexdigest() == expected, "PILOT_HASH_MISMATCH")
        hashes[name] = expected
    check({"protocol.json", "summary.json"} <= hashes.keys(), "PILOT_MANIFEST_INCOMPLETE")
    protocol, summary = a2.read(source / "protocol.json"), a2.read(source / "summary.json")
    check(protocol["stage"] == "pilot" and protocol["order"] == order(True), "PILOT_ORDER_INVALID")
    check(
        summary["complete"]
        and len(summary["attempts"]) == 3
        and all(row["usable"] and row["scenario_passed"] for row in summary["attempts"]),
        "PILOT_NOT_COMPLETE",
    )
    check(protocol["environment"] == config.identity(), "PILOT_ENVIRONMENT_CHANGED")
    check(
        protocol["provenance"]["script_hashes"] == provenance["script_hashes"]
        and protocol["provenance"]["application_sha"] == provenance["application_sha"],
        "PILOT_IMPLEMENTATION_CHANGED",
    )


def main(argv=None):
    parser = flow.SafeParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--stage", choices=("pilot", "evaluation"), required=True)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--pilot-source", type=Path)
    args = parser.parse_args(argv)
    try:
        check(sys.version_info[:2] == (3, 12), "PYTHON_VERSION_MISMATCH")
        config = Config.load(args.config)
        check(
            (
                config.operation_seconds,
                config.rollout_seconds,
                config.flow_seconds,
                config.poll_seconds,
            )
            == (600, 90, 90, 1),
            "PROTOCOL_LIMITS_CHANGED",
        )
        provenance = a1.provenance()
        check(
            not provenance["working_tree_dirty"] and provenance["infra_sha"] == args.expected_sha,
            "SOURCE_CHANGED",
        )
        check(
            not args.output.exists() and not args.output.with_suffix(".zip").exists(),
            "OUTPUT_ALREADY_EXISTS",
        )
        pilot_reference = None
        if args.stage == "evaluation":
            validate_pilot(args.pilot_source, config, provenance)
            pilot_reference = {
                "directory": args.pilot_source.name,
                "summary_sha256": hashlib.sha256(
                    (args.pilot_source / "summary.json").read_bytes()
                ).hexdigest(),
                "protocol_sha256": hashlib.sha256(
                    (args.pilot_source / "protocol.json").read_bytes()
                ).hexdigest(),
            }
        campaign.host_check(Runtime(config))
        if args.check_only:
            print(
                json.dumps(
                    {
                        "prepared": True,
                        "planned_attempts": len(order(args.stage == "pilot")),
                        "mutation": False,
                    }
                )
            )
            return 0
        secret = os.environ.get("CARRIER_ALPHA_WEBHOOK_SECRET", "")
        check(bool(secret), "MISSING_CARRIER_SECRET")
        with environment_lock(config), campaign.awake():
            args.output.mkdir()
            result = execute(
                config,
                args.config.resolve(),
                args.output.resolve(),
                provenance,
                secret,
                args.stage == "pilot",
                pilot_reference,
            )
            campaign.export(
                args.output.resolve(),
                result,
                csv_fields=[
                    "number",
                    "scenario",
                    "pair",
                    "condition",
                    "usable",
                    "scenario_passed",
                    "error",
                    "deployment_verdict",
                    "policy_action",
                    "automatic_restore",
                    "accepted_pending_events",
                    "completed_pending_events",
                    "accepted_observed_events",
                    "completed_observed_events",
                    "preparation_seconds",
                    "authorized_to_request_seconds",
                    "request_to_terminal_seconds",
                    "authorization_to_terminal_seconds",
                    "converged_seconds",
                    "notification_observed_seconds",
                    "signal_difference_seconds",
                ],
            )
        print(
            json.dumps(
                {
                    "complete": result["complete"],
                    "error": result["error"],
                    "attempts": len(result["attempts"]),
                    "output": str(args.output),
                }
            )
        )
        return 0 if result["complete"] else 6
    except ERRORS as error:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": error.code
                    if isinstance(error, flow.Failure)
                    else "PREPARATION_OR_EXPORT_FAILED",
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
