"""Campaign ordering, partial evidence, bounds and operational isolation."""

import contextlib
import dataclasses
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import a2
from scripts import a2_campaign as c
from scripts.a1_runtime import write_json
from scripts.verify_flow import Failure
from tests.test_a1 import config


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a2 comparison ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.provenance = {"infra_sha": "frozen", "working_tree_dirty": False}

    def fake_attempt(self, cfg, config_path, folder, case, secret, provenance):
        folder.mkdir()
        journal = a2.Journal(folder)
        journal.emit("candidate_send_intent")
        journal.emit("candidate_decided")
        bad = case["scenario"] == "invalid-pool"
        if bad:
            journal.emit(
                "restoration_requested",
                actor="script" if case["condition"] == "explicit" else "policy",
            )
            journal.emit("restore_send_intent")
            journal.emit("healthy_converged")
            journal.emit("recovery_observed")
        journal.emit("operation_finished")
        return {
            "scenario_passed": True,
            "deployment_verdict": "rejected" if bad else "approved",
            "automatic_restore": bad and case["condition"] == "auto",
            "restoration": "verified" if bad else "requires_explicit_restore_command",
            "recovery": {"recovery_passed": True},
        }

    @contextlib.contextmanager
    def lab(self, **overrides):
        with contextlib.ExitStack() as stack:
            mocks = {}
            for name, value in {
                "host_check": None,
                "prepare_runtime": None,
                "health": {"base": "fixed"},
                "cleanup": None,
                "power_identity": {"available": False},
            }.items():
                mocks[name] = stack.enter_context(patch.object(c, name, return_value=value))
            mocks["attempt"] = stack.enter_context(
                patch.object(c, "attempt", side_effect=overrides.get("attempt", self.fake_attempt))
            )
            stack.enter_context(patch.object(c.a1, "provenance", return_value=self.provenance))
            stack.enter_context(patch.object(c.Runtime, "preflight"))
            mocks["pause"] = stack.enter_context(
                patch.object(c.a1, "lifecycle", return_value={"scenario_passed": True})
            )
            yield mocks

    def run_campaign(self):
        return c.campaign(
            config(), self.root / "config.json", self.root, self.provenance, "never-export-secret"
        )

    def test_real_explicit_request_process_drives_existing_policy_under_lock(self):
        from scripts.a1_runtime import environment_lock
        from tests.test_a2 import Laboratory

        cfg = self.root / "config.json"
        write_json(cfg, dataclasses.asdict(config()))
        folder = self.root / "real request"
        instances = []

        def factory(config_value, journal):
            runtime = Laboratory(folder)
            runtime.journal = journal
            runtime.preflight = lambda: None
            instances.append(runtime)
            return runtime

        def flow(runtime, destination, secret, **kwargs):
            destination.mkdir()
            result = {
                "success": True,
                "verdict": "approved",
                "acceptance_verified": True,
                "checkpoint": {"event_id": "test"},
            }
            write_json(destination / "result.json", result)
            return result

        with (
            environment_lock(config()),
            patch.object(c.a2, "ObservedRuntime", side_effect=factory),
            patch.object(c.a2.a1_flow, "verify", side_effect=flow),
        ):
            result = c.attempt(
                config(),
                cfg,
                folder,
                {"condition": "explicit", "scenario": "invalid-pool"},
                "never-export-secret",
                self.provenance,
            )
        self.assertTrue(result["scenario_passed"])
        self.assertEqual(len(instances[0].patches), 2)
        self.assertEqual(a2.read(folder / "restore-request.json")["actor"], "script")
        self.assertTrue(a2.read(folder / "request/result.json")["request_recorded"])

    def test_guard_released_when_body_fails(self):
        kernel = Mock()
        kernel.SetThreadExecutionState.return_value = 1
        with (
            patch.object(c.os, "name", "nt"),
            patch.object(c.ctypes, "windll", Mock(kernel32=kernel), create=True),
        ):
            with self.assertRaisesRegex(RuntimeError, "injected"):
                with c.awake():
                    raise RuntimeError("injected")
        self.assertEqual(
            [x.args[0] for x in kernel.SetThreadExecutionState.call_args_list],
            [0x80000003, 0x80000000],
        )

    def test_energy_change_stops_before_attempt(self):
        with self.lab() as lab:
            lab["power_identity"].side_effect = [{"hash": "before"}, {"hash": "after"}]
            result = self.run_campaign()
        lab["attempt"].assert_not_called()
        self.assertEqual(result["error"], "POWER_CONFIGURATION_CHANGED")

    def test_bad_verdict_is_not_accepted_even_when_scenario_flag_true(self):
        def wrong(*args):
            result = self.fake_attempt(*args)
            result["deployment_verdict"] = "rejected"
            return result

        with self.lab(attempt=wrong) as lab:
            result = self.run_campaign()
        self.assertEqual(result["error"], "UNEXPECTED_VERDICT")
        lab["cleanup"].assert_not_called()
        self.assertFalse(result["attempts"][0]["usable"])

    def test_order_is_twenty_alternated_attempts_with_inverted_scenario_start(self):
        cases = c.order()
        self.assertEqual(len(cases), 20)
        self.assertEqual([x["number"] for x in cases], list(range(1, 21)))
        for start in (0, 10):
            pairs = [cases[i : i + 2] for i in range(start, start + 10, 2)]
            self.assertTrue(
                all({x["condition"] for x in pair} == {"auto", "explicit"} for pair in pairs)
            )
            self.assertTrue(
                all(pairs[i][0]["condition"] != pairs[i + 1][0]["condition"] for i in range(4))
            )
        self.assertNotEqual(cases[0]["condition"], cases[10]["condition"])

    def test_twenty_attempts_cleanup_only_healthy_and_pause_once(self):
        with self.lab() as lab:
            result = self.run_campaign()
        self.assertTrue(result["complete"])
        self.assertEqual(lab["attempt"].call_count, 20)
        self.assertEqual(lab["cleanup"].call_count, 10)
        lab["pause"].assert_called_once()
        self.assertEqual(len(result["paired_differences"]), 10)
        self.assertTrue((self.root / "protocol-hash.json").exists())

    def test_unexpected_failure_stops_without_replacement_or_speculative_restore(self):
        def fail(*args):
            raise Failure("UNCERTAIN_SEND")

        with self.lab(attempt=fail) as lab:
            result = self.run_campaign()
        self.assertFalse(result["complete"])
        self.assertEqual(len(result["attempts"]), 1)
        lab["cleanup"].assert_not_called()
        lab["pause"].assert_called_once()
        self.assertEqual(result["error"], "UNCERTAIN_SEND")

    def test_cleanup_failure_does_not_start_next_attempt_or_count_usable_pair(self):
        with self.lab() as lab:
            lab["cleanup"].side_effect = Failure("CLEANUP_FAILED")
            result = self.run_campaign()
        self.assertEqual(len(result["attempts"]), 1)
        self.assertFalse(result["attempts"][0]["usable"])
        self.assertEqual(result["groups"][0]["metrics"]["policy_total_seconds"]["n"], 0)

    def test_window_reserves_closure_and_stops_before_attempt(self):
        with self.lab() as lab, patch.object(c, "WINDOW", 100):
            result = self.run_campaign()
        lab["attempt"].assert_not_called()
        lab["pause"].assert_called_once()
        self.assertEqual(result["error"], "WINDOW_RESERVE_REACHED")

    def test_baseline_drift_stops_before_mutation(self):
        with self.lab() as lab:
            lab["health"].side_effect = [{"base": "fixed"}, {"base": "changed"}]
            result = self.run_campaign()
        lab["attempt"].assert_not_called()
        self.assertEqual(result["error"], "BASELINE_CHANGED")

    def test_shutdown_failure_keeps_comparison_incomplete(self):
        with self.lab() as lab:
            lab["pause"].side_effect = Failure("NO_API")
            result = self.run_campaign()
        self.assertFalse(result["complete"])
        self.assertEqual(result["shutdown"]["error"], "PAUSE_FAILED_INSPECT_LAB")

    def test_foreign_container_stops_without_touching_environment(self):
        with self.lab() as lab:
            lab["host_check"].side_effect = Failure("OTHER_CONTAINERS_RUNNING")
            result = self.run_campaign()
        lab["prepare_runtime"].assert_not_called()
        lab["pause"].assert_not_called()
        self.assertFalse(result["complete"])

    def test_monotonic_durations_reject_cross_process_comparison(self):
        records = [
            {"phase": "a", "process_id": "first", "elapsed_seconds": 2},
            {"phase": "b", "process_id": "second", "elapsed_seconds": 4},
        ]
        with self.assertRaisesRegex(Failure, "INCOMPARABLE_CLOCKS"):
            c.elapsed(records, "a", "b")

    def test_failed_attempt_never_gets_success_duration(self):
        journal = a2.Journal(self.root)
        journal.emit("candidate_send_intent")
        journal.emit("candidate_decided")
        result = c.measures(self.root, {"scenario_passed": False})
        self.assertTrue(all(result[x] is None for x in c.METRICS))

    def test_partial_summary_preserves_denominators_and_pair_direction(self):
        rows = [
            {
                "scenario": "healthy",
                "condition": condition,
                "pair": 1,
                "scenario_passed": True,
                "usable": True,
                **{m: value for m in c.METRICS},
            }
            for condition, value in [("auto", 2), ("explicit", 5)]
        ]
        result = c.aggregate(rows)
        self.assertEqual(
            result["paired_differences"][0]["auto_minus_explicit_seconds"]["policy_total_seconds"],
            -3,
        )
        self.assertEqual(result["groups"][0]["planned"], 5)
        self.assertEqual(result["groups"][0]["attempted"], 1)
        self.assertEqual(result["groups"][2]["attempted"], 0)

    def test_export_keeps_partial_rows_and_verifies_archive_no_overwrite(self):
        result = {"attempts": [], "complete": False}
        c.export(self.root, result)
        self.addCleanup(self.root.with_suffix(".zip").unlink)
        self.assertTrue(self.root.with_suffix(".zip").is_file())
        self.assertEqual(a2.read(self.root / "summary.json"), result)
        with self.assertRaises(FileExistsError):
            c.export(self.root, result)

    def test_request_is_separate_process_with_no_secret_argument_or_environment(self):
        write_json(self.root / "awaiting-request.json", {"attempt_id": "test"})
        errors = []
        with (
            patch.dict(os.environ, {"CARRIER_ALPHA_WEBHOOK_SECRET": "never-export-secret"}),
            patch.object(c.subprocess, "run", return_value=Mock(returncode=0)) as run,
        ):
            c.explicit_command(self.root / "config.json", self.root, threading.Event(), errors)
        self.assertFalse(errors)
        self.assertIn("--actor", run.call_args.args[0])
        self.assertEqual(run.call_args.args[0][-1], "script")
        self.assertNotIn("CARRIER_ALPHA_WEBHOOK_SECRET", run.call_args.kwargs["env"])
        self.assertNotIn("never-export-secret", repr(run.call_args))

    def test_check_only_never_starts_cluster_or_requires_secret(self):
        cfg = self.root / "config.json"
        write_json(cfg, dataclasses.asdict(config()))
        with (
            patch.object(c.a1, "provenance", return_value=self.provenance),
            patch.object(c, "host_check"),
            patch.object(c, "campaign") as run,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = c.main(
                [
                    "--config",
                    str(cfg),
                    "--output",
                    str(self.root / "new"),
                    "--expected-sha",
                    "frozen",
                    "--check-only",
                ]
            )
        self.assertEqual(code, 0)
        run.assert_not_called()
        self.assertFalse((self.root / "new").exists())

    def test_dirty_or_wrong_reference_refuses_before_host(self):
        cfg = self.root / "config.json"
        write_json(cfg, dataclasses.asdict(config()))
        with (
            patch.object(
                c.a1, "provenance", return_value={**self.provenance, "working_tree_dirty": True}
            ),
            patch.object(c, "host_check") as host,
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = c.main(
                [
                    "--config",
                    str(cfg),
                    "--output",
                    str(self.root / "new"),
                    "--expected-sha",
                    "frozen",
                    "--check-only",
                ]
            )
        self.assertEqual(code, 2)
        host.assert_not_called()

    def test_launcher_real_powershell_check_does_not_read_secret(self):
        pwsh = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
        self.assertIsNotNone(pwsh)
        shutil.copyfile(
            c.ROOT / "scripts/Invoke-A2Comparison.ps1", self.root / "Invoke-A2Comparison.ps1"
        )
        (self.root / "a2_campaign.py").write_text(
            "import sys,json; print(json.dumps(sys.argv[1:])); sys.exit(7)"
        )
        cfg = self.root / "config.json"
        cfg.write_text("{}")
        settings = self.root / "settings local.json"
        write_json(
            settings,
            {
                "python": sys.executable,
                "config": str(cfg),
                "output": str(self.root / "new output"),
                "expected_sha": "frozen",
                "secret_file": str(self.root / "missing-secret"),
            },
        )
        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(self.root / "Invoke-A2Comparison.ps1"),
                "-SettingsFile",
                str(settings),
                "-Mode",
                "Check",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn("--check-only", json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
