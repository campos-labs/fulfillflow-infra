"""Guard offered demand, metric failures and deadline interpretation."""

import math
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.scale_calibration import (
    exclusive,
    load_journal_finished,
    records,
    verify_images,
    wait_api,
)
from scripts.scale_contract import metric, outcome, schedule
from scripts.scale_environment import executable


class ScaleContracts(unittest.TestCase):
    def test_api_startup_retries_then_accepts_readiness(self):
        with (
            patch(
                "scripts.scale_calibration.environment.kubectl",
                side_effect=[RuntimeError("starting"), "ok"],
            ) as call,
            patch("scripts.scale_calibration.time.sleep"),
        ):
            wait_api(Path("unused"))
        self.assertEqual(call.call_count, 2)

    def test_api_startup_is_bounded(self):
        with patch("scripts.scale_calibration.time.monotonic", side_effect=[0, 121]):
            with self.assertRaisesRegex(RuntimeError, "KUBERNETES_API_STARTUP_TIMEOUT"):
                wait_api(Path("unused"))

    def test_missing_private_directory_is_not_recreated(self):
        with TemporaryDirectory() as folder:
            private = Path(folder) / "missing"
            with self.assertRaisesRegex(RuntimeError, "PRIVATE_DIRECTORY_UNAVAILABLE"):
                with exclusive(private):
                    self.fail("entered missing directory")
            self.assertFalse(private.exists())

    def test_process_exit_cannot_complete_an_older_journal_snapshot(self):
        snapshot = [{"kind": "response", "status": 202}]
        self.assertFalse(load_journal_finished(snapshot))
        self.assertTrue(load_journal_finished(snapshot + [{"kind": "load_finished"}]))

    def test_missing_executable_identifies_name(self):
        with patch("scripts.scale_environment.shutil.which", return_value=None):
            with self.assertRaises(FileNotFoundError) as caught:
                executable("missing-tool")
        self.assertEqual(caught.exception.filename, "missing-tool")

    def test_windows_docker_fallback_without_path_mutation(self):
        with (
            patch("scripts.scale_environment.shutil.which", return_value=None),
            patch("scripts.scale_environment.WINDOWS", True),
            patch("scripts.scale_environment.Path.is_file", return_value=True),
        ):
            self.assertTrue(
                executable("docker")
                .replace("\\", "/")
                .endswith("Docker/Docker/resources/bin/docker.exe")
            )

    def test_schedule_keeps_open_arrival_offsets(self):
        self.assertEqual(
            schedule([{"seconds": 2, "rate": 2}, {"seconds": 1, "rate": 1}]), [0, 0.5, 1, 1.5, 2]
        )

    def test_reject_unbounded_or_invalid_load(self):
        for value in (0, -1, math.inf, math.nan, True, 11):
            with self.subTest(value=value), self.assertRaises(ValueError):
                schedule([{"seconds": 10, "rate": value}])
        with self.assertRaises(ValueError):
            schedule([{"seconds": 60, "rate": 10}] * 2)

    def test_missing_metric_is_not_zero(self):
        for value in (None, {}, {"eligible": 0}):
            with self.assertRaises(ValueError):
                metric(value)

    def test_metric_retains_blocked_and_retry_separately(self):
        value = {
            "eligible": 2,
            "waiting_retry": 3,
            "blocked": 1,
            "done": 4,
            "oldest_eligible_seconds": 0.5,
        }
        self.assertEqual(metric(value), value)
        for invalid in (math.nan, -1, True):
            with self.assertRaises(ValueError):
                metric({**value, "eligible": invalid})

    def test_deadline_does_not_claim_loss(self):
        self.assertEqual(outcome(10, 70, 60, False, False), "completed_in_time")
        self.assertEqual(outcome(10, 71, 60, False, False), "completed_late")
        self.assertEqual(outcome(10, None, 60, True, True), "inconclusive")
        self.assertEqual(outcome(10, None, 60, False, True), "pending_at_end")
        self.assertEqual(outcome(10, None, 60, False, False), "inconclusive")
        with self.assertRaises(ValueError):
            outcome(10, 9, 60, False, False)

    def test_empty_pod_inventory_cannot_pass_identity(self):
        with patch("scripts.scale_calibration.environment.kubectl", return_value='{"items": []}'):
            with self.assertRaisesRegex(RuntimeError, "RUNTIME_INCOMPLETE"):
                verify_images(
                    Path("unused"),
                    {
                        "image_id": "sha256:582a858debe2ff64d481e810b2d5ae5a1aba6a669516bca36a15eb12e77ec072"
                    },
                )

    def test_lock_prevents_concurrent_mutation_without_removing_owner(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)
            with exclusive(path):
                with self.assertRaises(FileExistsError):
                    with exclusive(path):
                        self.fail("second owner acquired lock")
                self.assertTrue((path / "calibration.lock").exists())
            self.assertFalse((path / "calibration.lock").exists())

    def test_partial_journal_line_is_not_parsed_as_complete(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "admission.jsonl"
            self.assertEqual(records(path), [])
            path.write_text('{"kind":"offered"}\n{"kind":', encoding="utf-8")
            self.assertEqual(records(path), [{"kind": "offered"}])


if __name__ == "__main__":
    unittest.main()
