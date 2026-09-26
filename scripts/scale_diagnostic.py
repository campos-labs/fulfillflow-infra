"""Opt-in instrumentation for one fixed-replica run; no change to business checks."""

import json
import math
import re
import time
from urllib.parse import urlsplit

from scripts import scale_environment as env
from scripts.scale_contract import CLUSTER, TARGET, utc

METRICS = (
    "container_cpu_cfs_periods_total",
    "container_cpu_cfs_throttled_periods_total",
    "container_cpu_cfs_throttled_seconds_total",
)
CONTAINERS = {
    "core",
    "core-worker",
    "tracking",
    "tracking-worker",
    "notifications",
    "notifications-worker",
}
LINE = re.compile(r"(container_cpu_cfs_[a-z_]+)\{(.*)\} ([^ ]+) ([0-9]+)$")
LABEL = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*")')


def parse_throttling(text):
    rows = []
    for line in text.splitlines():
        match = LINE.fullmatch(line)
        if not match or match[1] not in METRICS:
            continue
        labels = {k: json.loads(v) for k, v in LABEL.findall(match[2])}
        if labels.get("namespace") != "fulfillflow" or labels.get("container") not in CONTAINERS:
            continue
        value = float(match[3])
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("INVALID_THROTTLING_COUNTER")
        rows.append(
            {
                "metric": match[1],
                "value": value,
                "source_timestamp_ms": int(match[4]),
                **{key: labels[key] for key in ("pod", "container", "id")},
            }
        )
    # Pod aggregates (empty container label) are deliberately excluded.
    for container in sorted(CONTAINERS):
        if {r["metric"] for r in rows if r["container"] == container} != set(METRICS):
            raise RuntimeError("THROTTLING_METRIC_UNAVAILABLE_" + container)
    return rows


def throttling_sample(private):
    start = time.monotonic()
    text = env.kubectl(
        private,
        ["get", "--raw", "/api/v1/nodes/" + CLUSTER + "-control-plane/proxy/metrics/cadvisor"],
        timeout=10,
    )
    return {
        "observed_at": utc(),
        "request_start_monotonic": start,
        "request_end_monotonic": time.monotonic(),
        "counters": parse_throttling(text),
    }


def wait_throttling(
    private,
    journal,
    *,
    seconds=90,
    sample=throttling_sample,
    monotonic=time.monotonic,
    sleep=time.sleep,
):
    """Bounded startup readiness only; missing measurements never become zero."""
    started = monotonic()
    deadline = started + seconds
    with journal.open("x", encoding="utf-8") as stream:
        while monotonic() < deadline:
            try:
                result = sample(private)
            except RuntimeError as error:
                code = str(error)
                if not code.startswith("THROTTLING_METRIC_UNAVAILABLE_"):
                    stream.write(
                        json.dumps(
                            {
                                "utc": utc(),
                                "elapsed_seconds": monotonic() - started,
                                "available": False,
                                "error": "PREFLIGHT_NONRETRYABLE",
                            }
                        )
                        + "\n"
                    )
                    stream.flush()
                    raise
                stream.write(
                    json.dumps(
                        {
                            "utc": utc(),
                            "elapsed_seconds": monotonic() - started,
                            "available": False,
                            "error": code,
                        }
                    )
                    + "\n"
                )
                stream.flush()
                sleep(max(0, min(5, deadline - monotonic())))
            else:
                stream.write(
                    json.dumps(
                        {"utc": utc(), "elapsed_seconds": monotonic() - started, "available": True}
                    )
                    + "\n"
                )
                stream.flush()
                return result
    raise RuntimeError("THROTTLING_PREFLIGHT_TIMEOUT")


def characterization_settings(
    settings,
    peak_rate,
    *,
    diagnostic,
    reuse,
    controlled,
    extension,
    http_concurrency=8,
    plateau_seconds=30,
):
    """Keep the historical profile unchanged; allow only explicitly bounded successors."""
    if plateau_seconds not in (30, 45) or (
        plateau_seconds == 45 and (peak_rate != 12 or http_concurrency != 16)
    ):
        raise RuntimeError("CHARACTERIZATION_DURATION_NOT_ALLOWED")
    if http_concurrency not in (8, 16) or (http_concurrency != 8 and peak_rate != 12):
        raise RuntimeError("ADMISSION_CONCURRENCY_PROFILE_NOT_ALLOWED")
    if peak_rate == 8:
        return settings
    if peak_rate not in (12, 16):
        raise RuntimeError("CHARACTERIZATION_RATE_NOT_ALLOWED")
    if not diagnostic or not reuse or not controlled or extension:
        raise RuntimeError("CHARACTERIZATION_REQUIRES_CONTROLLED_FIXED_DIAGNOSTIC")
    if settings["stages"] != [
        {"seconds": 15, "rate": 2},
        {"seconds": 30, "rate": 8},
        {"seconds": 15, "rate": 2},
    ]:
        raise RuntimeError("CHARACTERIZATION_BASELINE_CHANGED")
    return {
        **settings,
        "stages": [
            dict(s, rate=peak_rate, seconds=plateau_seconds) if i == 1 else dict(s)
            for i, s in enumerate(settings["stages"])
        ],
        "replicas": [1],
        "capacity_characterization": True,
        "http_concurrency": http_concurrency,
        "purpose": "bounded fixed-one capacity characterization; not formal comparison",
    }


def require_fixed_target(private):
    hpas = json.loads(env.kubectl(private, ["get", "hpa", "-o", "json"]))["items"]
    if any(h["spec"]["scaleTargetRef"]["name"] == TARGET for h in hpas):
        raise RuntimeError("DIAGNOSTIC_TARGET_HAS_HPA")
    # KEDA remains installed, but cannot mutate the target during this diagnostic.
    objects = json.loads(env.kubectl(private, ["get", "scaledobjects", "-o", "json"]))["items"]
    if any(o["spec"]["scaleTargetRef"]["name"] == TARGET for o in objects):
        raise RuntimeError("DIAGNOSTIC_TARGET_HAS_SCALEDOBJECT")


class TimedTransport:
    """Buffer timings per event; no extra fsync in the measured request path."""

    def __init__(self, transport):
        self.transport = transport
        self.records = []

    def __call__(self, method, url, headers, body, timeout):
        parts = urlsplit(url).path.split("/")
        allowed = {
            "carrier-events",
            "orders",
            "shipments",
            "notification-status",
            "notifications",
            "tracking-events",
        }
        endpoint = parts[3] if len(parts) > 3 and parts[3] in allowed else "other"
        row = {
            "method": method,
            "endpoint": endpoint,
            "started_at": utc(),
            "start_monotonic": time.monotonic(),
            "http_status": None,
            "error": None,
        }
        try:
            response = self.transport(method, url, headers, body, timeout)
            row["http_status"] = response.status
            return response
        except Exception as error:
            row["error"] = type(error).__name__
            raise
        finally:
            row["end_monotonic"] = time.monotonic()
            row["duration_seconds"] = row["end_monotonic"] - row["start_monotonic"]
            self.records.append(row)
