"""Verify published diagnostic evidence offline; never contacts Docker or the application."""

import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "docs/evidence/observability"


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    return json.loads(path.read_bytes())


def lines(path):
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def verify_case(base, case):
    directory = base / "records" / case
    review = read(base / (case + "-review.json"))
    functional = read(directory / "functional.json")
    protocol = read(directory / "protocol.json")
    observations = lines(directory / "event/observations.jsonl")
    workers = read(directory / "worker-records.json")
    http = read(directory / "http-timings.json")
    require(
        functional["success"] and read(directory / "shutdown.json")["container_stopped"],
        "CASE_INCOMPLETE",
    )
    require(protocol["infrastructure_sha"] == review["infrastructure_sha"], "REFERENCE_MISMATCH")
    require(protocol["runtime"]["source"] == review["application_sha"], "APPLICATION_MISMATCH")
    require(functional["event_id"] == review["event_id"], "EVENT_MISMATCH")
    require(sum(row["phase"] == "webhook_offered" for row in observations) == 1, "OFFER_COUNT")
    accepted = next(row for row in observations if row["phase"] == "accepted")
    confirmed = next(row for row in observations if row["phase"] == "notifications_simulated")
    checkpoints = functional["checkpoint"]
    records = [row for value in workers.values() for row in value["records"] if "message_id" in row]
    require(len(records) == 9, "WORKER_RECORD_COUNT")
    for row in records:
        require(
            row["event_id"] == checkpoints["tracking_event_id"]
            and row["correlation_id"] == checkpoints["inbox_event_id"]
            and row["request_id"] == accepted["request_id"],
            "CORRELATION_MISMATCH",
        )
    messages = {row["message_id"] for row in records}
    require(len(messages) == 3, "MESSAGE_COUNT")
    for message in messages:
        group = [row for row in records if row["message_id"] == message]
        require(
            Counter(row["outcome"] for row in group) == {"SENT": 1, "PERSISTED": 1, "DONE": 1},
            "MESSAGE_STAGES",
        )
    require(
        len(http) == review["http_requests"]
        and sum(row["http_status"] >= 400 for row in http) == review["http_errors"],
        "HTTP_COUNTS",
    )
    key = (
        "acceptance_to_notifications_confirmation_monotonic_seconds"
        if case == "healthy-01"
        else "acceptance_to_confirmation_monotonic_seconds"
    )
    require(
        round(confirmed["elapsed_seconds"] - accepted["elapsed_seconds"], 3) == review[key],
        "OBSERVED_INTERVAL",
    )
    if case == "pending-02":
        pending = next(row for row in observations if row["phase"] == "pending_confirmed")
        require(
            pending["publication"] == "SENT" and pending["processing"] == "NOT_RECEIVED",
            "PENDING_STATE",
        )
        public = next(
            row["response"]
            for row in observations
            if row["phase"] == "public_query"
            and row["operation"] == "notifications_pending_observation"
        )
        require(public == review["expected_pending_state"], "PENDING_PROJECTION")
        final = next(
            row["response"]
            for row in observations
            if row["phase"] == "public_query" and row["operation"] == "notifications_observation"
        )
        require(final == review["final_notification_state"], "FINAL_PROJECTION")
        require(pending["elapsed_seconds"] < confirmed["elapsed_seconds"], "PHASE_ORDER")
        transition = read(directory / "worker-transition.json")
        require(
            transition["before"]["notifications-worker"]["uid"]
            != transition["after"]["notifications-worker"]["uid"],
            "POD_NOT_REPLACED",
        )
        for worker in ("core-worker", "tracking-worker"):
            require(
                transition["before"][worker] == transition["after"][worker], "OTHER_WORKER_CHANGED"
            )
        require(
            read(directory / "restoration.json")["rollout_confirmed"], "RESTORATION_UNCONFIRMED"
        )
    return {"case": case, "event_records": len(records), "messages": len(messages)}


def verify(base=ROOT):
    base = base.resolve()
    manifest = read(base / "manifest.json")
    require(manifest["schema_version"] == 1, "MANIFEST_VERSION")
    declared = []
    for entry in manifest["files"]:
        path = (base / entry["path"]).resolve()
        require(path.is_relative_to(base / "records"), "MANIFEST_PATH")
        data = path.read_bytes()
        require(
            hashlib.sha256(data).hexdigest() == entry["sha256"] and len(data) == entry["bytes"],
            "EVIDENCE_HASH",
        )
        declared.append(path)
    actual = {path.resolve() for path in (base / "records").rglob("*") if path.is_file()}
    require(set(declared) == actual and len(declared) == len(actual), "MANIFEST_COVERAGE")
    for case in ("healthy-01", "pending-02"):
        review = read(base / (case + "-review.json"))
        for relative, digest in review["source_sha256"].items():
            path = base / "records" / case / relative
            if path.is_file():
                require(
                    hashlib.sha256(path.read_bytes()).hexdigest() == digest, "REVIEW_SOURCE_HASH"
                )
    results = [verify_case(base, case) for case in ("healthy-01", "pending-02")]
    failure = read(base / "records/preparation-failure-01/functional.json")
    require(
        failure["webhook_offered"] is False and failure["last_operation"] == "forwarding_preflight",
        "PREPARATION_FAILURE_SCOPE",
    )
    return {"files_verified": len(declared), "cases": results, "load_executed": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
