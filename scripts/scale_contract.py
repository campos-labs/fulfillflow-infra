"""Bounded calibration contracts; no cluster mutations or application imports."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

SOURCE = "9e3a135a00db218643633c7165d3106f0c8285e1"
CLUSTER = "fulfillflow-scale-01"
TARGET = "core-worker"
# OCI index 582a858d... resolves to manifest ffb7d2d4... and this config.
RUNTIME_CONFIG = "sha256:cc882fab4e5294ed7e516131a1b4ace90a2d7e019467ca5c929b14381b680daa"
# Counts include uncommitted in-flight rows: conservative runnable + busy demand.
QUERY = """SELECT json_build_object(
 'eligible', count(*) FILTER (WHERE state IN ('PENDING','RETRY_WAIT') AND next_attempt_at <= now()),
 'waiting_retry', count(*) FILTER (WHERE state='RETRY_WAIT' AND next_attempt_at > now()),
 'blocked', count(*) FILTER (WHERE state='BLOCKED'),
 'done', count(*) FILTER (WHERE state='DONE'),
 'oldest_eligible_seconds', COALESCE(EXTRACT(EPOCH FROM now()-min(created_at) FILTER
 (WHERE state IN ('PENDING','RETRY_WAIT') AND next_attempt_at <= now())),0))
 FROM message_inbox WHERE type='tracking.apply.v1';"""


def schedule(stages: list[dict]) -> list[float]:
    if not stages or len(stages) > 5:
        raise ValueError("INVALID_STAGES")
    result, offset = [], 0.0
    for stage in stages:
        seconds, rate = stage["seconds"], stage["rate"]
        if any(type(x) not in (int, float) or not math.isfinite(x) for x in (seconds, rate)):
            raise ValueError("INVALID_STAGE_NUMBER")
        if not 1 <= seconds <= 60 or not 0 < rate <= 10:
            raise ValueError("STAGE_LIMIT")
        count = math.floor(seconds * rate)
        result.extend(offset + i / rate for i in range(count))
        offset += seconds
    if not result or len(result) > 600 or offset > 180:
        raise ValueError("LOAD_LIMIT")
    return result


def metric(value: object) -> dict:
    keys = {"eligible", "waiting_retry", "blocked", "done", "oldest_eligible_seconds"}
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError("METRIC_SCHEMA")
    for key, number in value.items():
        if type(number) not in (int, float) or not math.isfinite(number) or number < 0:
            raise ValueError("METRIC_VALUE")
        if key != "oldest_eligible_seconds" and type(number) is not int:
            raise ValueError("METRIC_COUNT")
    return value


def outcome(
    accepted: float,
    completed: float | None,
    deadline: float,
    observation_error: bool,
    pending_confirmed: bool,
) -> str:
    if completed is not None:
        if completed < accepted:
            raise ValueError("INVALID_CLOCK_ORDER")
        return "completed_in_time" if completed - accepted <= deadline else "completed_late"
    if observation_error:
        return "inconclusive"
    return "pending_at_end" if pending_confirmed else "inconclusive"


def write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def utc() -> str:
    return datetime.now(UTC).isoformat()
