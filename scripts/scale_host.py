"""Opt-in notebook power evidence, separate from application success."""

import json
import os
import threading
import time

from scripts import scale_environment as env
from scripts.scale_contract import utc, write


def snapshot():
    import psutil

    battery = psutil.sensors_battery()
    cpu = psutil.cpu_times()
    return {
        "utc": utc(),
        "monotonic": time.monotonic(),
        "power_plugged": battery.power_plugged if battery else None,
        "battery_percent": battery.percent if battery else None,
        "host_available_bytes": psutil.virtual_memory().available,
        "host_cpu_user_seconds": cpu.user,
        "host_cpu_system_seconds": cpu.system,
    }


def power_plan():
    if os.name != "nt":
        return None
    return env.command(["powercfg", "/getactivescheme"], timeout=5).strip()


def assess(rows, initial_plan, final_plan, error=None):
    from datetime import datetime

    gaps = [b["monotonic"] - a["monotonic"] for a, b in zip(rows, rows[1:])]
    wall_gaps = [
        (datetime.fromisoformat(b["utc"]) - datetime.fromisoformat(a["utc"])).total_seconds()
        for a, b in zip(rows, rows[1:])
    ]
    reasons = []
    if error:
        reasons.append("HOST_MONITOR_ERROR")
    if len(rows) < 2:
        reasons.append("INSUFFICIENT_HOST_SAMPLES")
    if any(r["power_plugged"] is not True for r in rows):
        reasons.append("AC_NOT_CONFIRMED_THROUGHOUT")
    if not initial_plan or not final_plan or initial_plan != final_plan:
        reasons.append("POWER_PLAN_UNKNOWN_OR_CHANGED")
    if any(g <= 0 or g > 5 for g in gaps) or any(abs(a - b) > 1 for a, b in zip(gaps, wall_gaps)):
        reasons.append("HOST_SAMPLING_GAP_OR_CLOCK_DISCONTINUITY")
    return {
        "valid": not reasons,
        "reasons": reasons,
        "samples": len(rows),
        "initial_power_plan": initial_plan,
        "final_power_plan": final_plan,
        "max_sample_gap_seconds": max(gaps, default=None),
        "error": error,
        "limits": [
            "sampled power, not proof of exclusive host use",
            "power plan checked only at start/end; brief transitions may escape sampling",
            "no temperature or frequency monitoring; absolute CPU counters cover entire host",
        ],
    }


class HostMonitor:
    def __init__(self, output, sampler=snapshot, plan_reader=power_plan, interval=1):
        self.output, self.sampler, self.plan_reader = output, sampler, plan_reader
        self.interval = interval
        self.rows = []
        self.initial_plan = None
        self.error = None
        self.stop = threading.Event()
        self.thread = None
        self.stream = None

    def append(self):
        row = self.sampler()
        self.stream.write(json.dumps(row) + "\n")
        self.stream.flush()
        self.rows.append(row)
        return row

    def start(self):
        self.stream = (self.output / "host-conditions.jsonl").open("x", encoding="utf-8")
        self.initial_plan = self.plan_reader()
        first = self.append()
        if first["power_plugged"] is not True or not self.initial_plan:
            raise RuntimeError("HOST_AC_OR_POWER_PLAN_UNAVAILABLE")
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        try:
            while not self.stop.wait(self.interval):
                self.append()
        except Exception as error:
            self.error = type(error).__name__

    def close(self):
        self.stop.set()
        if self.thread:
            self.thread.join(timeout=5)
        final_plan = None
        try:
            if self.thread and self.thread.is_alive():
                self.error = "HOST_MONITOR_SHUTDOWN_TIMEOUT"
            else:
                if self.stream:
                    self.append()
                final_plan = self.plan_reader()
        except Exception as error:
            self.error = type(error).__name__
        finally:
            if self.stream and not (self.thread and self.thread.is_alive()):
                self.stream.close()
        result = assess(self.rows, self.initial_plan, final_plan, self.error)
        write(self.output / "host-review.json", result)
        return result
