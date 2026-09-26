"""Summarize the preserved focal run without changing its files or starting resources."""

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.scale_diagnostic import METRICS


def windows(series):
    groups = defaultdict(lambda: defaultdict(dict))
    for sample in series:
        for row in sample["throttling"]["counters"]:
            values = groups[(row["container"], row["pod"], row["id"])][row["metric"]]
            t, value = row["source_timestamp_ms"], row["value"]
            if t in values and values[t] != value:
                raise ValueError("CONFLICTING_SOURCE_TIMESTAMP")
            values[t] = value
    result = []
    for (container, pod, identity), metrics in sorted(groups.items()):
        row = {"container": container, "pod": pod, "cgroup": identity, "valid": False}
        if set(metrics) != set(METRICS) or len({tuple(sorted(v)) for v in metrics.values()}) != 1:
            row["reason"] = "missing or unaligned counters"
        else:
            times = sorted(metrics[METRICS[0]])
            reset = any(
                any(v[b] < v[a] for a, b in zip(times, times[1:])) for v in metrics.values()
            )
            if len(times) < 2 or reset:
                row["reason"] = "insufficient distinct timestamps or counter reset"
            else:
                delta = {k: v[times[-1]] - v[times[0]] for k, v in metrics.items()}
                periods, limited, seconds = (delta[k] for k in METRICS)
                row.update(
                    valid=True,
                    distinct_timestamps=len(times),
                    start_ms=times[0],
                    end_ms=times[-1],
                    window_seconds=(times[-1] - times[0]) / 1000,
                    periods=periods,
                    throttled_periods=limited,
                    throttled_seconds=seconds,
                    throttled_period_fraction=limited / periods if periods else None,
                )
        result.append(row)
    return result


def durations(values):
    values = sorted(values)
    if not values:
        return {"count": 0}
    return {
        "count": len(values),
        "median_seconds": statistics.median(values),
        "p95_seconds": values[math.ceil(0.95 * len(values)) - 1],
        "max_seconds": max(values),
    }


def review(source):
    manifest = source / "checksums.sha256"
    count = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ", 1)
        path = (source / name).resolve()
        if (
            not path.is_relative_to(source.resolve())
            or hashlib.sha256(path.read_bytes()).hexdigest() != digest
        ):
            raise ValueError("SOURCE_CHECKSUM_MISMATCH")
        count += 1
    load = source / "fixed-1"
    series = [json.loads(s) for s in (load / "series.jsonl").read_text().splitlines()]
    events = json.loads((load / "events.json").read_text())
    timings = [
        r for p in sorted(load.glob("event-*/http-timings.json")) for r in json.loads(p.read_text())
    ]
    by_endpoint = defaultdict(list)
    for r in timings:
        by_endpoint[r["endpoint"]].append(r["duration_seconds"])
    summary = json.loads((source / "summary.json").read_text())
    return {
        "source": str(source),
        "verified_files": count,
        "source_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "protocol": json.loads((source / "protocol.json").read_text()),
        "execution": summary,
        "functional": json.loads((load / "summary.json").read_text()),
        "throttling_windows": windows(series),
        "http": {
            "durations": durations([r["duration_seconds"] for r in timings]),
            "errors": sum(r["error"] is not None for r in timings),
            "non_200": sum(r["http_status"] != 200 for r in timings),
            "by_endpoint": {k: durations(v) for k, v in by_endpoint.items()},
        },
        "observed_latency": durations(
            [
                r["completed_monotonic"] - r["acceptance"]["monotonic"]
                for r in events
                if r.get("completed_monotonic")
            ]
        ),
        "terminal_verification_duration": durations(
            [
                r["completed_monotonic"] - r["observed_monotonic"]
                for r in events
                if r.get("completed_monotonic")
            ]
        ),
        "max_eligible": max(s["inbox"]["eligible"] for s in series),
        "max_oldest_eligible_seconds": max(s["inbox"]["oldest_eligible_seconds"] for s in series),
        "samples": len(series),
        "collection": durations([s["collection_end_monotonic"] - s["monotonic"] for s in series]),
        "cadvisor_collection": durations(
            [
                s["throttling"]["request_end_monotonic"]
                - s["throttling"]["request_start_monotonic"]
                for s in series
            ]
        ),
        "max_collection_overrun_seconds": max(s["interval_overrun_seconds"] for s in series),
        "limits": [
            "descriptive diagnostic, not a controlled comparison",
            "source windows differ across components and may include edge periods of preparation/drain",
            "throttled periods are not percent of lost CPU or application downtime",
            "HTTP timing excludes validation/fsync; concurrent durations cannot be summed as elapsed time",
            "no causal attribution of CPU consumption to observer or proof of global bottleneck",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.input.resolve()):
        raise ValueError("OUTPUT_MUST_BE_SEPARATE")
    result = review(args.input.resolve())
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({"reviewed": True, "files_verified": result["verified_files"]}))


if __name__ == "__main__":
    main()
