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
    for container in CONTAINERS:
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
