"""Read-only review of preserved scale evidence; never starts a workload."""

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


def cpu_reads(series, prefix):
    distinct = {}
    observed = 0
    for sample in series:
        for pod in sample["resources"]:
            if not pod["pod"].startswith(prefix):
                continue
            cpu = pod.get("cpu") or {}
            if "time" not in cpu or "usageNanoCores" not in cpu:
                continue
            observed += 1
            key = (pod["uid"], cpu["time"])
            value = cpu["usageNanoCores"] / 1e9
            if key in distinct and distinct[key] != value:
                raise ValueError("CONFLICTING_CPU_TIMESTAMP")
            distinct[key] = value
    return {
        "collected": observed,
        "distinct": len(distinct),
        "near_500m": sum(value >= 0.45 for value in distinct.values()),
        "readings": [
            {"uid": uid, "time": timestamp, "cores": value}
            for (uid, timestamp), value in distinct.items()
        ],
    }


def plateau_rows(series, start, seconds_from=15, seconds_to=45):
    selected = []
    previous = None
    for sample in series:
        instant = sample["inbox_observed_monotonic"]
        offset = instant - start
        row = {"offset_seconds": offset, **sample["inbox"]}
        if previous is not None:
            duration = instant - previous["inbox_observed_monotonic"]
            delta = sample["inbox"]["done"] - previous["inbox"]["done"]
            if duration <= 0 or delta < 0:
                raise ValueError("INVALID_COUNTER_INTERVAL")
            row.update(
                interval_seconds=duration,
                done_delta=delta,
                interval_fully_in_plateau=previous["inbox_observed_monotonic"] - start
                >= seconds_from,
                done_per_second=delta / duration,
            )
        if seconds_from <= offset < seconds_to:
            selected.append(row)
        previous = sample
    return selected


def review(source):
    inputs = []

    def read(path, lines=False):
        raw = path.read_bytes()
        inputs.append((str(path.relative_to(source)), hashlib.sha256(raw).hexdigest()))
        return (
            [json.loads(row) for row in raw.decode("utf-8").splitlines()]
            if lines
            else json.loads(raw)
        )

    admissions = read(source / "admission.jsonl", True)
    series = read(source / "series.jsonl", True)
    summary = read(source / "summary.json")
    settings = read(source / "load.json")
    if settings["stages"] != [
        {"seconds": 15, "rate": 2},
        {"seconds": 30, "rate": 8},
        {"seconds": 15, "rate": 2},
    ]:
        raise ValueError("UNSUPPORTED_PROFILE")
    start = next(r["scheduled_monotonic"] for r in admissions if r["kind"] == "dispatch_attempt")
    first_offer = next(
        datetime.fromisoformat(r["utc"]) for r in admissions if r["kind"] == "offered"
    )
    distribution, operations, statuses = Counter(), Counter(), Counter()
    total_get = total_preparation_post = 0
    evidence_files = sorted(source.glob("event-*/observations.jsonl"))
    for path in evidence_files:
        records = read(path, True)
        gets = [r for r in records if r.get("phase") == "http" and r.get("method") == "GET"]
        if any(datetime.fromisoformat(r["observed_at"]) < first_offer for r in gets):
            raise ValueError("GET_BEFORE_LOAD")
        distribution[len(gets)] += 1
        total_get += len(gets)
        operations.update(r["operation"] for r in gets)
        statuses.update(str(r["http_status"]) for r in gets)
        total_preparation_post += sum(
            r.get("phase") == "http" and r.get("method") == "POST" for r in records
        )
    prepared = read(source / "prepared.json")
    if len(evidence_files) != len(prepared):
        raise ValueError("EVIDENCE_COUNT")
    # Exact pod prefix excludes core-worker without assigning every API sample to it.
    api_prefix = "core-"
    api_series = [
        {**s, "resources": [r for r in s["resources"] if not r["pod"].startswith("core-worker-")]}
        for s in series
    ]
    return {
        "purpose": "retrospective diagnostic; not a new experiment",
        "functional_summary": summary,
        "observer": {
            "recorded_get_responses": total_get,
            "get_statuses": dict(statuses),
            "gets_per_event_distribution": dict(distribution),
            "operations": dict(operations),
            "preparation_posts_excluded": total_preparation_post,
        },
        "core_api_cpu": cpu_reads(api_series, api_prefix),
        "worker_cpu": cpu_reads(series, "core-worker-"),
        "plateau": plateau_rows(series, start),
        "limits": [
            "CPU source timestamps deduplicated; samples are not repetitions",
            "GET counts cover recorded responses, not unlogged transport failures",
            "done deltas cover the dedicated database, not per-event completion latency",
            "no preserved throttling counters; no attribution of CPU cause",
            "short sampled plateau cannot establish sustainable capacity",
        ],
    }, inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, target = args.input.resolve(), args.output.resolve()
    if target == source or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("OUTPUT_MUST_BE_SEPARATE")
    result, inputs = review(source)
    target.mkdir(exist_ok=False)
    (target / "review.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    (target / "source-checksums.sha256").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in inputs), encoding="utf-8"
    )
    print(json.dumps({"reviewed": True, "sources": len(inputs), "output": str(target)}))


if __name__ == "__main__":
    main()
