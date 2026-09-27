"""Explicit continuation of the interrupted comparison; frozen measurement code."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_comparison as cmp
from scripts.scale_contract import utc, write

REFERENCE = "6932632ecc07afbef844f6c7483cfc71d0b5799e"
ROOTS = ("scripts", "config", "k8s", "pyproject.toml", "uv.lock")
ADDITIONS = {"scripts/scale_continuation.py", "scripts/Invoke-ScaleContinuation.ps1"}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def verify_measurement():
    """Compare original runtime/config files, not just the protocol JSON."""
    old = set(
        cmp.env.command(
            ["git", "ls-tree", "-r", "--name-only", REFERENCE, "--", *ROOTS]
        ).splitlines()
    )
    current = set(cmp.env.command(["git", "ls-files", "--", *ROOTS]).splitlines())
    # Documentation is updated with the amendment; it is not consumed by the executor.
    old.discard("k8s/README.md")
    current.discard("k8s/README.md")
    if not old or current - old - ADDITIONS:
        raise RuntimeError("UNREVIEWED_MEASUREMENT_FILES")
    if cmp.env.command(["git", "diff", REFERENCE, "--", *sorted(old)]).strip():
        raise RuntimeError("QUALIFIED_MEASUREMENT_CHANGED")
    return len(old)


def verify_bundle(folder):
    required = {"comparison-result.json", "protocol.json", "shutdown.json", "summary.json"}
    seen = set()
    for line in (folder / "checksums.sha256").read_text().splitlines():
        expected, name = line.split(maxsplit=1)
        name = name.lstrip("*")
        path = (folder / name).resolve()
        if not path.is_relative_to(folder.resolve()) or name in seen:
            raise RuntimeError("INVALID_EVIDENCE_MANIFEST")
        seen.add(name)
        if cmp.digest(path) != expected:
            raise RuntimeError("EVIDENCE_HASH_MISMATCH")
    if not required.issubset(seen):
        raise RuntimeError("INCOMPLETE_EVIDENCE_MANIFEST")
    r = read(folder / "comparison-result.json")
    if (
        not r.get("execution_valid")
        or not r.get("shutdown_confirmed")
        or not r.get("host_conditions_valid")
    ):
        raise RuntimeError("INVALID_ATTEMPT_REQUIRES_REVIEW")
    if r["protocol_sha256"] != cmp.digest(cmp.CONFIG):
        raise RuntimeError("ATTEMPT_PROTOCOL_CHANGED")
    return r


def names():
    return [
        f"b{b}-p{p}-{c}"
        for b, block in enumerate(cmp.order(cmp.config()["seed"]), 1)
        for p, c in enumerate(block, 1)
    ]


def manifest(private, source):
    q = read(private / "comparison-qualified.json")
    if q["infra_sha"] != REFERENCE or q["protocol_sha256"] != cmp.digest(cmp.CONFIG):
        raise RuntimeError("QUALIFICATION_REFERENCE_CHANGED")
    qfolder = Path(q["source"]) / "qualification-fixed-1"
    qr = verify_bundle(qfolder)
    if (
        cmp.digest(qfolder / "comparison-result.json") != q["result_sha256"]
        or qr["accepted"] != 1020
        or qr["max_active_requests"] > 28
    ):
        raise RuntimeError("QUALIFICATION_HASH_OR_MARGIN")
    protocol = read(source / "protocol.json")
    if (
        protocol["infra_sha"] != REFERENCE
        or protocol["config"] != cmp.config()
        or protocol["order"] != cmp.order(cmp.config()["seed"])
    ):
        raise RuntimeError("SOURCE_PROTOCOL_CHANGED")
    if {p.name for p in source.iterdir()} != {"protocol.json", "progress-01.json", names()[0]}:
        raise RuntimeError("SOURCE_NOT_EXPECTED_ONE_ATTEMPT_PREFIX")
    first = verify_bundle(source / names()[0])
    if first["condition"] != "adaptive" or read(source / "progress-01.json") != {
        "attempts_completed": 1,
        "results": [first],
    }:
        raise RuntimeError("SOURCE_PROGRESS_MISMATCH")
    return {
        "amendment": "bounded-memory-wait-and-explicit-sessions-v1",
        "measurement_reference": REFERENCE,
        "qualified_runtime_files_verified": verify_measurement(),
        "protocol_sha256": cmp.digest(cmp.CONFIG),
        "baseline_marker_sha256": cmp.digest(private / "comparison-baseline.json"),
        "qualification_marker_sha256": cmp.digest(private / "comparison-qualified.json"),
        "source": str(source),
        "source_result_sha256": cmp.digest(source / names()[0] / "comparison-result.json"),
        "coordinator_sha256": cmp.digest(Path(__file__)),
        "launcher_sha256": cmp.digest(cmp.ROOT / "scripts/Invoke-ScaleContinuation.ps1"),
        "order": names(),
        "memory_wait_seconds": 180,
        "stable_samples": 3,
        "block_1_continuous": False,
        "interpretation": "Preserve all nine planned positions, including original late outcomes. Block 1 interrupted; do not represent this as the original uninterrupted blocked campaign. Session effects remain a limitation.",
    }


def completed(source, output):
    rows = [
        {
            "attempt": names()[0],
            "session": "original-interrupted",
            "path": str(source / names()[0]),
            "result": verify_bundle(source / names()[0]),
        }
    ]
    attempts = output / "attempts"
    if attempts.exists() and {p.name for p in attempts.iterdir()} - set(names()[1:]):
        raise RuntimeError("UNEXPECTED_ATTEMPT_FOLDER")
    gap = False
    for name in names()[1:]:
        folder = attempts / name
        if not folder.exists():
            gap = True
            continue
        if gap:
            raise RuntimeError("NONCONTIGUOUS_ATTEMPT_PREFIX")
        # An incomplete directory is never removed, retried or skipped.
        result = verify_bundle(folder)
        start = read(output / "starts" / (name + ".json"))
        if result["condition"] != name.split("-", 2)[2] or start["attempt"] != name:
            raise RuntimeError("ATTEMPT_IDENTITY_MISMATCH")
        rows.append(
            {"attempt": name, "session": start["session"], "path": str(folder), "result": result}
        )
    # A recorded start without evidence can mean interrupted execution; require review.
    starts = output / "starts"
    if starts.exists() and {p.stem for p in starts.iterdir()} != {r["attempt"] for r in rows[1:]}:
        raise RuntimeError("UNFINISHED_ATTEMPT_REQUIRES_REVIEW")
    return rows


def wait_memory(
    log,
    deadline,
    *,
    sample=cmp.snapshot,
    command=cmp.env.command,
    clock=time.monotonic,
    sleep=time.sleep,
):
    consecutive = 0
    end = min(deadline, clock() + 180)
    with log.open("x", encoding="utf-8") as stream:
        while True:
            if clock() >= end:
                raise RuntimeError("MEMORY_OR_SESSION_WAIT_EXHAUSTED")
            running = command(["docker", "ps", "--format", "{{.Names}}"], timeout=10).strip()
            row = sample()
            row["running_containers"] = running.splitlines()
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            if running or row.get("power_plugged") is not True:
                raise RuntimeError("HOST_NOT_IDLE_OR_AC_UNCONFIRMED")
            consecutive = consecutive + 1 if row["host_available_bytes"] >= 5 * 2**30 else 0
            if consecutive >= 3 and clock() < end:
                return
            sleep(min(5, max(0, end - clock())))


def summary(rows):
    return {
        "complete": len(rows) == 9,
        "attempts_completed": len(rows),
        "results": rows,
        "blocks": [
            {
                "block": b,
                "sessions": sorted(
                    {r["session"] for r in rows if r["attempt"].startswith(f"b{b}-")}
                ),
                "continuous": sum(r["attempt"].startswith(f"b{b}-") for r in rows) == 3
                and b != 1
                and len({r["session"] for r in rows if r["attempt"].startswith(f"b{b}-")}) == 1,
                "complete": sum(r["attempt"].startswith(f"b{b}-") for r in rows) == 3,
            }
            for b in range(1, 4)
        ],
        "limits": "Interrupted original block retained. Describe per-attempt/session outcomes; no claim of an uninterrupted blocked campaign, causal advantage, power or population inference.",
    }


def run(private, source, output, mode):
    cmp.require_context()
    if cmp.env.command(["git", "status", "--porcelain"]).strip():
        raise RuntimeError("DIRTY_CHECKOUT")
    if (private / "comparison-continuation.lock").exists():
        raise RuntimeError("CONTINUATION_ALREADY_LOCKED")
    expected = manifest(private, source)
    output.mkdir(parents=True, exist_ok=True)
    marker = output / "continuation.json"
    if marker.exists():
        if read(marker) != expected:
            raise RuntimeError("CONTINUATION_REFERENCE_CHANGED")
    else:
        if list(output.iterdir()):
            raise RuntimeError("OUTPUT_NOT_EMPTY")
        write(marker, expected)
    rows = completed(source, output)
    if mode == "check":
        print(
            json.dumps(
                {
                    "complete": True,
                    "load_executed": False,
                    "attempts_preserved": len(rows),
                    "remaining": 9 - len(rows),
                }
            )
        )
        return
    if len(rows) == 9:
        raise RuntimeError("CAMPAIGN_ALREADY_COMPLETE")
    # Separate lock from the frozen per-attempt calibration lock. Never reclaim stale locks.
    lock = private / "comparison-continuation.lock"
    with lock.open("x") as stream:
        stream.write(utc())
    try:
        session = utc().replace(":", "-")
        session_dir = output / "sessions" / session
        session_dir.mkdir(parents=True)
        write(
            session_dir / "start.json",
            {
                "utc": utc(),
                "infra_sha": cmp.env.command(["git", "rev-parse", "HEAD"]).strip(),
                "next_index": len(rows),
                "measurement_reference": REFERENCE,
            },
        )
        (output / "starts").mkdir(exist_ok=True)
        (output / "attempts").mkdir(exist_ok=True)
        began = time.monotonic()
        block = None
        block_began = began
        try:
            for name in names()[len(rows) :]:
                if name[:2] != block:
                    block, block_began = name[:2], time.monotonic()
                deadline = min(began + 160 * 60, block_began + 40 * 60)
                print(f"Waiting for host margin before {name} (up to 180 seconds)", flush=True)
                wait_memory(session_dir / (name + "-memory.jsonl"), deadline)
                if time.monotonic() >= deadline:
                    raise RuntimeError("SESSION_WINDOW_EXHAUSTED")
                verify_measurement()
                if time.monotonic() >= deadline:
                    raise RuntimeError("SESSION_WINDOW_EXHAUSTED")
                start = {"attempt": name, "session": session, "utc": utc()}
                write(output / "starts" / (name + ".json"), start)
                print(f"Continuation: {name}; no retry", flush=True)
                cmp.one(private, output / "attempts" / name, name.split("-", 2)[2])
                rows = completed(source, output)
                write(session_dir / (name + "-result.json"), summary(rows))
            write(output / "comparison-summary.json", summary(rows))
            print(
                json.dumps(
                    {"complete": True, "attempts_completed": len(rows), "output": str(output)}
                )
            )
        except Exception as error:
            write(
                session_dir / "stop.json",
                {
                    "utc": utc(),
                    "error": type(error).__name__,
                    "code": str(error)
                    if isinstance(error, RuntimeError)
                    else "CONTINUATION_FAILED",
                    "attempts_preserved": len(rows),
                },
            )
            raise
        finally:
            write(
                session_dir / "end.json",
                {"utc": utc(), "elapsed_seconds": time.monotonic() - began},
            )
    finally:
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mode", choices=("check", "execute"), default="check")
    args = parser.parse_args()
    try:
        private, source, output = (
            args.private.resolve(),
            args.source.resolve(),
            args.output.resolve(),
        )
        if private.is_relative_to(cmp.ROOT) or any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for a, b in ((private, source), (private, output), (source, output))
        ):
            raise RuntimeError("PATH_OVERLAP")
        run(private, source, output, args.mode)
        return 0
    except Exception as error:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": type(error).__name__,
                    "code": str(error)
                    if isinstance(error, RuntimeError)
                    else "CONTINUATION_FAILED",
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
