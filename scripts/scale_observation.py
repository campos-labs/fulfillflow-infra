"""Independent sampled telemetry and allowlisted worker attribution."""

import json
import os
import threading
import time

from scripts import scale_environment as env
from scripts.scale_contract import CLUSTER, TARGET, utc, write


def process_resources():
    import psutil

    parent = psutil.Process(os.getpid())
    rows = []
    for process in [parent, *parent.children(recursive=True)]:
        try:
            cpu = process.cpu_times()
            rows.append(
                {
                    "pid": process.pid,
                    "created": process.create_time(),
                    "name": process.name(),
                    "cpu_seconds": cpu.user + cpu.system,
                    "rss_bytes": process.memory_info().rss,
                }
            )
        except psutil.NoSuchProcess:
            continue
    memory = psutil.virtual_memory()
    return {
        "processes": rows,
        "host_available_bytes": memory.available,
        "host_total_bytes": memory.total,
        "scope": "sampled process tree; short-lived processes may be absent; overlaps node resources",
    }


def temporal_sample(private, replicas, inbox):
    sample = {"utc": utc(), "monotonic": time.monotonic(), "replicas_fixed": replicas}
    sample["inbox"] = inbox()
    sample["inbox_observed_monotonic"] = time.monotonic()
    dep = json.loads(
        env.kubectl(private, ["get", "deployment/" + TARGET, "-o", "json"], timeout=10)
    )
    sample["deployment"] = {
        "uid": dep["metadata"]["uid"],
        "desired": dep["spec"]["replicas"],
        "ready": dep["status"].get("readyReplicas", 0),
    }
    stats = json.loads(
        env.kubectl(
            private,
            ["get", "--raw", "/api/v1/nodes/" + CLUSTER + "-control-plane/proxy/stats/summary"],
            timeout=10,
        )
    )
    sample["resources"] = [
        {
            "namespace": p["podRef"]["namespace"],
            "pod": p["podRef"]["name"],
            "uid": p["podRef"]["uid"],
            "cpu": p.get("cpu"),
            "memory": p.get("memory"),
        }
        for p in stats.get("pods", [])
    ]
    sample["node_resources"] = {k: stats["node"].get(k) for k in ("cpu", "memory")}
    sample["instrument"] = process_resources()
    sample["collection_end_monotonic"] = time.monotonic()
    return sample


class Collector:
    def __init__(self, path, sample, interval):
        self.path, self.sample, self.interval = path, sample, interval
        self.stop = threading.Event()
        self.failed = threading.Event()
        self.ready = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)

    def run(self):
        try:
            with self.path.open("x", encoding="utf-8") as stream:
                while not self.stop.is_set():
                    tick = time.monotonic()
                    record = self.sample()
                    record["interval_overrun_seconds"] = max(
                        0, time.monotonic() - tick - self.interval
                    )
                    stream.write(json.dumps(record) + "\n")
                    stream.flush()
                    self.ready.set()
                    self.stop.wait(max(0, self.interval - (time.monotonic() - tick)))
        except Exception as error:
            self.failed.set()
            write(
                self.path.with_suffix(".error.json"),
                {"error": type(error).__name__, "metric_unknown": True},
            )
        finally:
            self.ready.set()

    def start(self):
        self.thread.start()
        if not self.ready.wait(45) or self.failed.is_set():
            self.close()
            raise RuntimeError("COLLECTION_START_FAILED")

    def close(self):
        self.stop.set()
        self.thread.join(timeout=45)
        if self.thread.is_alive():
            raise RuntimeError("COLLECTION_SHUTDOWN_TIMEOUT")


def worker_pods(private):
    items = json.loads(
        env.kubectl(
            private,
            ["get", "pods", "-l", "app.kubernetes.io/name=" + TARGET, "-o", "json"],
            timeout=10,
        )
    )["items"]
    return [
        {
            "name": p["metadata"]["name"],
            "uid": p["metadata"]["uid"],
            "restarts": sum(
                c.get("restartCount", 0) for c in p["status"].get("containerStatuses", [])
            ),
        }
        for p in items
    ]


def matching_records(text, request_ids):
    selected = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not isinstance(record, dict):
            continue
        if (
            record.get("service") == "core"
            and record.get("stage") == "process"
            and record.get("outcome") == "DONE"
            and record.get("request_id") in request_ids
        ):
            selected.append(
                {
                    k: record.get(k)
                    for k in (
                        "timestamp",
                        "request_id",
                        "event_id",
                        "message_id",
                        "outcome",
                        "duration_ms",
                    )
                }
            )
    return selected


def attribution(private, before, since, admissions, path):
    after = worker_pods(private)
    ids = {r["request_id"] for r in admissions.values() if r.get("request_id")}
    selected = []
    for pod in after:
        text = env.kubectl(private, ["logs", pod["name"], "--since-time=" + since], timeout=15)
        selected.extend(
            {**record, "pod_uid": pod["uid"], "pod": pod["name"]}
            for record in matching_records(text, ids)
        )
    counts = {key: sum(r["request_id"] == key for r in selected) for key in ids}
    result = {
        "source": "frozen application post-transaction process DONE logs",
        "before": before,
        "after": after,
        "records": selected,
        "matched_requests": len(counts),
        "accepted": len(admissions),
        "complete": sorted(before, key=lambda p: p["uid"]) == sorted(after, key=lambda p: p["uid"])
        and len(ids) == len(admissions)
        and all(n == 1 for n in counts.values()),
        "per_pod": {p["name"]: sum(r["pod_uid"] == p["uid"] for r in selected) for p in after},
    }
    write(path, result)
    return result


def wait_worker_count(private, replicas):
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        pods = worker_pods(private)
        if len(pods) == replicas:
            return pods
        time.sleep(2)
    raise RuntimeError("WORKER_POD_COUNT")
