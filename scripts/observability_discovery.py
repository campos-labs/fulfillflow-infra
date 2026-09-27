"""Correlate a declared sample from published evidence; no cluster or trace synthesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SELECTION = "prepared[0] in each attempt, regardless of outcome; illustrative, not representative"
UNAVAILABLE = (
    "durable_trace_context",
    "tracking_commit_time",
    "notifications_commit_time",
    "publication_to_durable_receipt_interval",
    "telemetry_export_health",
)


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def one(rows: list[dict], reason: str) -> dict | None:
    require(len(rows) <= 1, reason)
    return rows[0] if rows else None


def finite(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def correlate(
    prepared: dict,
    event: dict,
    admission: list[dict],
    attribution: list[dict],
    observations: list[dict],
    queries: list[dict],
) -> dict:
    """Missing evidence stays missing; conflicting identities reject the correlation."""
    for key in ("event_id", "order_id", "shipment_id"):
        require(prepared.get(key) is not None, "PREPARED_ID_MISSING")
        require(prepared[key] == event.get(key), "EVENT_IDENTITY_MISMATCH")
    accepted = event.get("acceptance")
    if accepted:
        require(accepted.get("event_id") == event["event_id"], "ACCEPTANCE_EVENT_MISMATCH")
        require(accepted.get("status") == 202, "ACCEPTANCE_STATUS_MISMATCH")
        require(bool(accepted.get("request_id")), "ACCEPTANCE_ID_MISSING")
    responses = [
        row
        for row in admission
        if row.get("event_id") == event["event_id"]
        and row.get("kind") == "response"
        and row.get("status") == 202
    ]
    response = one(responses, "AMBIGUOUS_ACCEPTANCE")
    if accepted and response:
        for key in ("request_id", "inbox_id", "monotonic", "utc"):
            require(accepted.get(key) == response.get(key), "ACCEPTANCE_JOURNAL_MISMATCH")
    request_id = accepted.get("request_id") if accepted else None
    worker = one(
        [r for r in attribution if request_id and r.get("request_id") == request_id],
        "AMBIGUOUS_WORKER_RECORD",
    )
    if worker and event.get("tracking_event_id"):
        require(worker.get("event_id") == event["tracking_event_id"], "WORKER_EVENT_MISMATCH")
    for row in observations:
        if row.get("phase") == "order_created":
            require(row.get("order_id") == event["order_id"], "OBSERVATION_ORDER_MISMATCH")
        if row.get("phase") == "shipment_created":
            require(row.get("shipment_id") == event["shipment_id"], "OBSERVATION_SHIPMENT_MISMATCH")
        if row.get("phase") in ("tracking_completed", "notifications_simulated"):
            require(
                row.get("tracking_event_id") == event.get("tracking_event_id"),
                "OBSERVATION_TRACKING_MISMATCH",
            )
        if row.get("phase") == "notifications_simulated":
            require(
                row.get("notification_id") == event.get("notification_id"),
                "OBSERVATION_NOTIFICATION_MISMATCH",
            )
    gets = [q for q in queries if q.get("method") == "GET"]
    for q in gets:
        start, end = q.get("start_monotonic"), q.get("end_monotonic")
        require(finite(start) and finite(end) and end >= start, "INVALID_HTTP_INTERVAL")
    gets.sort(key=lambda q: q["start_monotonic"])
    phase_names = ("tracking_completed", "business_completed", "notifications_simulated")
    marks = [
        {k: row[k] for k in ("phase", "observed_at") if k in row}
        for row in observations
        if row.get("phase") in phase_names
    ]
    coverage = {
        "acceptance_linked_to_journal": bool(accepted and response),
        "core_done_linked_to_business_event": bool(
            worker and event.get("tracking_event_id") and worker.get("outcome") == "DONE"
        ),
        "tracking_confirmation_observed": any(m.get("phase") == phase_names[0] for m in marks),
        "business_confirmation_observed": any(m.get("phase") == phase_names[1] for m in marks),
        "notifications_confirmation_observed": any(m.get("phase") == phase_names[2] for m in marks),
        "observer_http_intervals": bool(gets),
    }
    return {
        "external_event_id": event["event_id"],
        "business_event_id": event.get("tracking_event_id"),
        "admission_request_id": request_id,
        "original_classification": event.get("classification"),
        "coverage": coverage,
        "acceptance": {k: accepted.get(k) for k in ("utc", "monotonic")} if accepted else None,
        "core_process_record": (
            {k: worker.get(k) for k in ("timestamp", "duration_ms", "message_id", "outcome")}
            if worker
            else None
        ),
        "observed_marks": marks,
        "observer_http": {
            "get_count": len(gets),
            "non_200": sum(
                type(q.get("http_status")) is int and q["http_status"] != 200 for q in gets
            ),
            "transport_errors_or_unknown": sum(
                q.get("http_status") is None or q.get("error") is not None for q in gets
            ),
            "first_get_monotonic": gets[0]["start_monotonic"] if gets else None,
            "last_get_end_monotonic": gets[-1]["end_monotonic"] if gets else None,
            "queries_sharing_admission_request_id": sum(
                bool(request_id) and q.get("sent_request_id") == request_id for q in gets
            ),
            "request_response_id_matches": sum(
                bool(q.get("sent_request_id"))
                and q.get("sent_request_id") == q.get("response_request_id")
                for q in gets
            ),
        },
        "completed_observer_monotonic": event.get("completed_monotonic"),
        "unavailable_in_selected_sources": list(UNAVAILABLE),
    }


def discover(evidence: Path) -> dict:
    manifest_bytes = (evidence / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    results = []
    for archive in manifest["archives"]:
        path = evidence / archive["path"]
        require(path.resolve().is_relative_to(evidence.resolve()), "ARCHIVE_OUTSIDE_EVIDENCE")
        require(digest(path.read_bytes()) == archive["sha256"], "ARCHIVE_HASH_MISMATCH")
        with zipfile.ZipFile(path) as z:
            require(len(z.namelist()) == len(set(z.namelist())), "DUPLICATE_ZIP_MEMBER")
            for attempt in manifest["attempts"]:
                if attempt["archive"] != archive["path"]:
                    continue
                prefix = attempt["root"] + "/measurement/"

                def read(name: str):
                    return json.loads(z.read(prefix + name))

                def lines(name: str):
                    return [json.loads(row) for row in z.read(prefix + name).splitlines() if row]

                prepared = read("prepared.json")[0]
                event = one(
                    [e for e in read("events.json") if e["event_id"] == prepared["event_id"]],
                    "AMBIGUOUS_SELECTED_EVENT",
                )
                require(event is not None, "SELECTED_EVENT_MISSING")
                result = correlate(
                    prepared,
                    event,
                    lines("admission.jsonl"),
                    read("worker-attribution.json")["records"],
                    lines("event-0000/observations.jsonl"),
                    read("event-0000/http-timings.json"),
                )
                results.append(
                    {
                        "attempt": attempt["attempt"],
                        "source_archive": archive["path"],
                        "source_prefix": prefix,
                        **result,
                    }
                )
    require(len(results) == len(manifest["attempts"]), "ATTEMPT_COVERAGE_MISMATCH")
    coverage = Counter(k for r in results for k, present in r["coverage"].items() if present)
    return {
        "schema_version": 1,
        "complete": True,
        "load_executed": False,
        "tracing_tested": False,
        "selection": SELECTION,
        "selected_events": len(results),
        "source_manifest_sha256": digest(manifest_bytes),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "application_reference": manifest["application_reference"],
        "measurement_reference": manifest["measurement_reference"],
        "coverage_selected_events": dict(coverage),
        "limits": [
            "Observed marks are query confirmations, not persisted completion timestamps.",
            "Monotonic values retain their original load-generator or observer clock domain.",
            "Worker UTC timestamps are not subtracted from observer clocks.",
            "No spans are synthesized; identifier correlation is not propagated tracing.",
            "Missing telemetry does not prove absence of processing.",
            "This selection illustrates join feasibility, not the distribution of delays.",
        ],
        "events": results,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "docs/evidence/scaling")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "OUTPUT_ALREADY_EXISTS")
    result = discover(args.evidence)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({k: result[k] for k in ("complete", "load_executed", "selected_events")}))


if __name__ == "__main__":
    main()
