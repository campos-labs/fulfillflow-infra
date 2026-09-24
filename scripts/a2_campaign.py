"""Frozen 20-attempt A2 comparison on the existing Kind lab; no replacement runs."""

from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import os
import statistics
import subprocess
import sys
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import a1, a2
from scripts.a1_runtime import ROOT, Config, Runtime, check, digest, environment_lock, write_json
from scripts.verify_flow import Failure, SafeParser

WINDOW = 4 * 3600
RESERVE = 1800  # Cleanup, shutdown and bounded pre/post checks after an attempt.
METRICS = (
    "candidate_decision_seconds",
    "activation_seconds",
    "configuration_recovery_seconds",
    "functional_recovery_seconds",
    "policy_total_seconds",
)


def order() -> list[dict]:
    result = []
    for scenario_index, scenario in enumerate(("healthy", "invalid-pool")):
        for pair in range(1, 6):
            conditions = (
                ("explicit", "auto") if (pair + scenario_index) % 2 else ("auto", "explicit")
            )
            for condition in conditions:
                result.append(
                    {
                        "number": len(result) + 1,
                        "scenario": scenario,
                        "pair": pair,
                        "condition": condition,
                    }
                )
    return result


def elapsed(records: list[dict], start: str, end: str) -> float | None:
    left = [r for r in records if r["phase"] == start]
    right = [r for r in records if r["phase"] == end]
    if not left or not right:
        return None
    a, b = left[0], right[0]
    check(a["process_id"] == b["process_id"], "INCOMPARABLE_CLOCKS")
    delta = b["elapsed_seconds"] - a["elapsed_seconds"]
    check(delta >= 0, "INVALID_DURATION")
    return delta


def measures(folder: Path, result: dict) -> dict:
    records = a2.Journal(folder).records
    passed = result.get("scenario_passed") is True
    # An interrupted/failed attempt never contributes a duration of success.
    values = dict.fromkeys(METRICS)
    if passed:
        values["candidate_decision_seconds"] = elapsed(
            records, "candidate_send_intent", "candidate_decided"
        )
        values["policy_total_seconds"] = elapsed(
            records, "candidate_send_intent", "operation_finished"
        )
        if result.get("restoration") == "verified":
            values["activation_seconds"] = elapsed(
                records, "candidate_decided", "restoration_requested"
            )
            values["configuration_recovery_seconds"] = elapsed(
                records, "restoration_requested", "healthy_converged"
            )
            values["functional_recovery_seconds"] = elapsed(
                records, "restoration_requested", "recovery_observed"
            )
    return {
        **values,
        "restore_intents": sum(r["phase"] == "restore_send_intent" for r in records),
        "restoration_actors": [
            r["actor"] for r in records if r["phase"] == "restoration_requested"
        ],
    }


def aggregate(rows: list[dict]) -> dict:
    groups = []
    pairs = []
    for scenario in ("healthy", "invalid-pool"):
        for condition in ("explicit", "auto"):
            selected = [
                r for r in rows if r["scenario"] == scenario and r["condition"] == condition
            ]
            metrics = {}
            for key in METRICS:
                numbers = [
                    r[key]
                    for r in selected
                    if r.get("usable") and r.get("scenario_passed") and r.get(key) is not None
                ]
                metrics[key] = {
                    "n": len(numbers),
                    "median": statistics.median(numbers) if numbers else None,
                    "min": min(numbers) if numbers else None,
                    "max": max(numbers) if numbers else None,
                }
            groups.append(
                {
                    "scenario": scenario,
                    "condition": condition,
                    "planned": 5,
                    "attempted": len(selected),
                    "passed": sum(r.get("scenario_passed") is True for r in selected),
                    "usable": sum(r.get("usable") is True for r in selected),
                    "metrics": metrics,
                }
            )
        for pair in range(1, 6):
            selected = {
                r["condition"]: r
                for r in rows
                if r["scenario"] == scenario
                and r["pair"] == pair
                and r.get("usable")
                and r.get("scenario_passed")
            }
            if set(selected) == {"auto", "explicit"}:
                pairs.append(
                    {
                        "scenario": scenario,
                        "pair": pair,
                        "auto_minus_explicit_seconds": {
                            k: selected["auto"][k] - selected["explicit"][k]
                            for k in METRICS
                            if selected["auto"].get(k) is not None
                            and selected["explicit"].get(k) is not None
                        },
                    }
                )
    return {"groups": groups, "paired_differences": pairs}


def health(runtime: Runtime) -> dict:
    runtime.preflight()
    inventory = runtime.inventory()
    stateful = runtime.get("statefulsets")["items"]
    check(
        {x["metadata"]["name"] for x in stateful} == {"postgres", "rabbitmq"},
        "STATEFUL_SET_MISMATCH",
    )
    for item in runtime.get("deployments")["items"] + stateful:
        check(
            item["spec"]["replicas"] == item.get("status", {}).get("readyReplicas") == 1,
            "WORKLOAD_NOT_READY",
        )
        check(
            item.get("status", {}).get("observedGeneration", 0) >= item["metadata"]["generation"],
            "GENERATION_NOT_OBSERVED",
        )
    pvcs = [
        {"name": x["metadata"]["name"], "uid": x["metadata"]["uid"], "phase": x["status"]["phase"]}
        for x in runtime.get("pvc")["items"]
    ]
    check(len(pvcs) == 2 and all(x["phase"] == "Bound" for x in pvcs), "VOLUME_NOT_BOUND")
    return {
        "inventory": inventory,
        "stateful": {
            x["metadata"]["name"]: {
                "uid": x["metadata"]["uid"],
                "template": digest(x["spec"]["template"]),
            }
            for x in stateful
        },
        "pvcs": sorted(pvcs, key=lambda x: x["name"]),
        "references": a2.references(runtime),
    }


def prepare_runtime(config: Config, output: Path) -> None:
    runtime = Runtime(config)
    info = json.loads(runtime.command([config.docker, "inspect", config.node]))[0]
    check(
        info["Config"].get("Labels", {}).get("io.x-k8s.kind.cluster") == config.context[5:],
        "DOCKER_NODE_MISMATCH",
    )
    if not info["State"]["Running"]:
        runtime.command([config.docker, "start", config.node], timeout=45)
    deadline = time.monotonic() + 60
    while True:
        try:
            runtime.kubectl("get", "--raw=/readyz")
            break
        except Failure:
            check(time.monotonic() < deadline, "LOCAL_API_UNAVAILABLE")
            time.sleep(2)
    runtime.preflight()
    write_json(output / "result.json", a1.lifecycle(runtime, output, "resume"))


def explicit_command(
    config_path: Path, folder: Path, stop: threading.Event, errors: list[str]
) -> None:
    try:
        while not stop.wait(0.1):
            if (folder / "awaiting-request.json").exists():
                env = os.environ.copy()
                env.pop("CARRIER_ALPHA_WEBHOOK_SECRET", None)
                with (
                    (folder / "request.stdout.log").open("x") as out,
                    (folder / "request.stderr.log").open("x") as err,
                ):
                    response = subprocess.run(
                        [
                            sys.executable,
                            str(ROOT / "scripts/a2.py"),
                            "--config",
                            str(config_path),
                            "--output",
                            str(folder / "request"),
                            "--mode",
                            "request",
                            "--source",
                            str(folder),
                            "--actor",
                            "script",
                        ],
                        stdout=out,
                        stderr=err,
                        env=env,
                        timeout=30,
                    )
                check(response.returncode == 0, "EXPLICIT_REQUEST_FAILED")
                return
    except (Failure, OSError, subprocess.SubprocessError):
        errors.append("EXPLICIT_REQUEST_FAILED")


def attempt(
    config: Config, config_path: Path, folder: Path, case: dict, secret: str, provenance: dict
) -> dict:
    folder.mkdir()
    write_json(folder / "identity.json", {**provenance, "environment": config.identity(), **case})
    journal = a2.Journal(folder)
    runtime = a2.ObservedRuntime(config, journal)
    stop, errors = threading.Event(), []
    helper = None
    if case["condition"] == "explicit" and case["scenario"] == "invalid-pool":
        helper = threading.Thread(
            target=explicit_command, args=(config_path, folder, stop, errors), daemon=True
        )
        helper.start()
    try:
        runtime.preflight()
        journal.emit("operation_started", mode="run")
        result = a2.run(runtime, folder, case["condition"], case["scenario"], secret)
        check(not errors, "EXPLICIT_REQUEST_FAILED")
        journal.emit("operation_finished", success=result["scenario_passed"])
        write_json(folder / "result.json", result)
        return result
    except (
        Failure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        if not (folder / "result.json").exists():
            write_json(
                folder / "result.json",
                {
                    "scenario_passed": False,
                    "error": error.code
                    if isinstance(error, Failure)
                    else "INTERRUPTED_OR_OPERATION_FAILED",
                    "retry": False,
                },
            )
        raise
    finally:
        stop.set()
        if helper:
            helper.join(35)
            check(not helper.is_alive(), "REQUEST_PROCESS_UNRESOLVED")


def cleanup(config: Config, folder: Path, secret: str) -> None:
    output = folder / "cleanup"
    output.mkdir()
    runtime = a2.ObservedRuntime(config, a2.Journal(folder))
    runtime.preflight()
    runtime.journal.emit("restoration_requested", actor="script", cleanup=True)
    result = a2.recover(runtime, folder, output, secret)
    write_json(output / "result.json", result)
    check(result["recovery_passed"], "CLEANUP_NOT_VERIFIED")


@contextmanager
def awake():
    # Thread-scoped inhibition only, no persistent Windows power-plan change.
    if os.name != "nt":
        yield
        return
    kernel = ctypes.windll.kernel32
    check(bool(kernel.SetThreadExecutionState(0x80000003)), "WAKE_GUARD_FAILED")
    try:
        yield
    finally:
        kernel.SetThreadExecutionState(0x80000000)


def host_check(runtime: Runtime) -> None:
    running = runtime.command([runtime.config.docker, "ps", "--format", "{{.Names}}"])
    check(set(running.splitlines()) <= {runtime.config.node}, "OTHER_CONTAINERS_RUNNING")
    if os.name == "nt":

        class Power(ctypes.Structure):
            _fields_ = [
                ("ac", ctypes.c_ubyte),
                ("flag", ctypes.c_ubyte),
                ("percent", ctypes.c_ubyte),
                ("reserved", ctypes.c_ubyte),
                ("life", ctypes.c_ulong),
                ("full", ctypes.c_ulong),
            ]

        power = Power()
        check(
            bool(ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(power)))
            and power.ac == 1,
            "AC_POWER_REQUIRED",
        )


def power_identity() -> dict:
    if os.name != "nt":
        return {"available": False}
    command = str(Path(os.environ["SystemRoot"]) / "System32/powercfg.exe")
    response = subprocess.run([command, "/query"], capture_output=True, timeout=30)
    check(response.returncode == 0, "POWER_QUERY_FAILED")
    # Preserve comparison over original bytes, independent of console encoding.
    return {
        "available": True,
        "query_sha256": hashlib.sha256(response.stdout).hexdigest(),
        "query": response.stdout.decode(f"cp{ctypes.windll.kernel32.GetOEMCP()}", errors="replace"),
    }


def export(root: Path, summary: dict) -> None:
    write_json(root / "summary.json", summary)
    rows = summary["attempts"]
    with (root / "attempts.csv").open("x", encoding="utf-8", newline="") as stream:
        fields = [
            "number",
            "scenario",
            "pair",
            "condition",
            "scenario_passed",
            "usable",
            "deployment_verdict",
            "error",
            "campaign_error",
            *METRICS,
            "restore_intents",
            "cleanup_passed",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    hashes = {
        p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }
    with (root / "checksums.sha256").open("x", encoding="utf-8") as stream:
        stream.writelines(f"{value}  {name}\n" for name, value in hashes.items())
    archive = root.with_suffix(".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(root.rglob("*")):
            if p.is_file():
                bundle.write(p, root.name + "/" + p.relative_to(root).as_posix())
    with zipfile.ZipFile(archive) as bundle:
        check(bundle.testzip() is None, "ARCHIVE_CORRUPT")
        for name, expected in hashes.items():
            check(
                hashlib.sha256(bundle.read(root.name + "/" + name)).hexdigest() == expected,
                "ARCHIVE_HASH_MISMATCH",
            )


def campaign(
    config: Config, config_path: Path, output: Path, provenance: dict, secret: str
) -> dict:
    started = time.monotonic()
    rows, error, shutdown = [], None, None
    touched = False
    row = None
    try:
        host_check(Runtime(config))
        touched = True
        resume = output / "resume"
        resume.mkdir()
        prepare_runtime(config, resume)
        baseline = health(Runtime(config))
        power = power_identity()
        protocol = {
            "version": 1,
            "provenance": provenance,
            "environment": config.identity(),
            "baseline": baseline,
            "order": order(),
            "deadlines_seconds": {
                "window": WINDOW,
                "operation": 600,
                "rollout": 90,
                "flow": 90,
                "poll": 1,
                "closure_reserve": RESERVE,
                "explicit_request_poll": 0.1,
            },
            "actor": "script",
            "scope": "Kind A2-II, no Azure or application load campaign",
            "host": {
                "platform": sys.platform,
                "python": sys.version.split()[0],
                "windows_idle_inhibition": os.name == "nt",
                "power": power,
            },
            "started_utc": datetime.now(UTC).isoformat(),
        }
        write_json(output / "protocol.json", protocol)
        write_json(output / "protocol-hash.json", {"sha256_canonical_json": digest(protocol)})
        for case in protocol["order"]:
            row = None
            check(time.monotonic() - started + 600 + RESERVE < WINDOW, "WINDOW_RESERVE_REACHED")
            check(a1.provenance() == provenance, "SOURCE_CHANGED")
            host_check(Runtime(config))
            check(power_identity() == power, "POWER_CONFIGURATION_CHANGED")
            check(health(Runtime(config)) == baseline, "BASELINE_CHANGED")
            folder = output / f"{case['number']:02d}-{case['scenario']}-{case['condition']}"
            row = {**case, "scenario_passed": False, "usable": False, **dict.fromkeys(METRICS)}
            rows.append(row)
            print(f"A2 {case['number']}/20: {case['scenario']} / {case['condition']}", flush=True)
            result = attempt(config, config_path, folder, case, secret, provenance)
            row.update(
                {k: result.get(k) for k in ("scenario_passed", "deployment_verdict", "error")}
            )
            row.update(
                measures(folder, result)
            )  # Before separate healthy cleanup adds another clock.
            check(result["scenario_passed"], "ATTEMPT_FAILED")
            check(
                result["deployment_verdict"]
                == ("approved" if case["scenario"] == "healthy" else "rejected"),
                "UNEXPECTED_VERDICT",
            )
            if case["scenario"] == "healthy":
                check(
                    not result.get("automatic_restore") and row["restore_intents"] == 0,
                    "UNEXPECTED_RESTORE",
                )
                cleanup(config, folder, secret)
                row["cleanup_passed"] = True
            else:
                check(
                    result.get("recovery", {}).get("recovery_passed")
                    and row["restore_intents"] == 1
                    and result.get("automatic_restore") == (case["condition"] == "auto"),
                    "RECOVERY_NOT_VERIFIED",
                )
            host_check(Runtime(config))
            check(power_identity() == power, "POWER_CONFIGURATION_CHANGED")
            check(health(Runtime(config)) == baseline, "BASELINE_NOT_RESTORED")
            row["usable"] = True
            write_json(folder / "campaign-row.json", row)
        write_json(output / "final-health.json", health(Runtime(config)))
    except (
        Failure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as caught:
        error = caught.code if isinstance(caught, Failure) else "INTERRUPTED_OR_OPERATION_FAILED"
        if row is not None:
            row["campaign_error"] = error
            row["usable"] = False
    finally:
        if touched:
            try:
                pause = output / "pause"
                pause.mkdir()
                runtime = Runtime(config)
                runtime.preflight()
                shutdown = a1.lifecycle(runtime, pause, "pause")
                write_json(pause / "result.json", shutdown)
            except (
                Failure,
                OSError,
                ValueError,
                KeyError,
                TypeError,
                subprocess.SubprocessError,
                KeyboardInterrupt,
            ):
                shutdown = {"scenario_passed": False, "error": "PAUSE_FAILED_INSPECT_LAB"}
    return {
        "complete": len(rows) == 20
        and error is None
        and bool(shutdown and shutdown["scenario_passed"]),
        "error": error,
        "attempts": rows,
        **aggregate(rows),
        "shutdown": shutdown,
        "elapsed_seconds": time.monotonic() - started,
        "limits": [
            "Explicit activation by script, not human reaction",
            "Single-node Kind, no capacity or AKS claim",
            "Startup failure offers no event before recovery",
            "Same-host archive is not independent backup",
            "No automatic retry or replacement; incomplete series remains incomplete",
        ],
    }


def main(argv=None) -> int:
    parser = SafeParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        check(sys.version_info[:2] == (3, 12), "PYTHON_VERSION_MISMATCH")
        config = Config.load(args.config)
        check(
            (
                config.operation_seconds,
                config.rollout_seconds,
                config.flow_seconds,
                config.poll_seconds,
            )
            == (600, 90, 90, 1),
            "PROTOCOL_LIMITS_CHANGED",
        )
        provenance = a1.provenance()
        check(
            not provenance["working_tree_dirty"] and provenance["infra_sha"] == args.expected_sha,
            "SOURCE_CHANGED",
        )
        check(
            not args.output.exists() and not args.output.with_suffix(".zip").exists(),
            "OUTPUT_ALREADY_EXISTS",
        )
        host_check(Runtime(config))
        if args.check_only:
            print(json.dumps({"prepared": True, "planned_attempts": 20, "mutation": False}))
            return 0
        secret = os.environ.get("CARRIER_ALPHA_WEBHOOK_SECRET", "")
        check(bool(secret), "MISSING_CARRIER_SECRET")
        with environment_lock(config), awake():
            args.output.mkdir()
            result = campaign(
                config, args.config.resolve(), args.output.resolve(), provenance, secret
            )
            export(args.output.resolve(), result)
        print(
            json.dumps(
                {
                    "complete": result["complete"],
                    "error": result["error"],
                    "attempts": len(result["attempts"]),
                    "output": str(args.output),
                }
            )
        )
        return 0 if result["complete"] else 6
    except (
        Failure,
        OSError,
        ValueError,
        KeyError,
        TypeError,
        subprocess.SubprocessError,
        KeyboardInterrupt,
    ) as error:
        print(
            json.dumps(
                {
                    "error": error.code
                    if isinstance(error, Failure)
                    else "OPERATION_OR_EXPORT_FAILED",
                    "retry": False,
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
