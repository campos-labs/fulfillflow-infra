"""Power evidence is independent of functional completion and never assumes missing means AC."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from scripts.scale_calibration import _execute
from scripts.scale_host import HostMonitor, assess


def row(seconds, plugged=True):
    return {
        "utc": f"2026-09-26T10:00:{seconds:02d}+00:00",
        "monotonic": float(seconds),
        "power_plugged": plugged,
    }


class HostTests(unittest.TestCase):
    def test_stable_ac_has_no_qualification_reasons(self):
        self.assertTrue(assess([row(0), row(1)], "same", "same")["valid"])

    def test_missing_or_battery_sample_is_not_valid(self):
        for plugged in (False, None):
            result = assess([row(0), row(1, plugged)], "same", "same")
            self.assertFalse(result["valid"])
            self.assertIn("AC_NOT_CONFIRMED_THROUGHOUT", result["reasons"])

    def test_gap_plan_change_and_monitor_error_are_explicit(self):
        result = assess([row(0), row(8)], "before", "after", "OSError")
        self.assertEqual(
            set(result["reasons"]),
            {
                "HOST_MONITOR_ERROR",
                "POWER_PLAN_UNKNOWN_OR_CHANGED",
                "HOST_SAMPLING_GAP_OR_CLOCK_DISCONTINUITY",
            },
        )

    def test_unknown_plan_and_clock_discontinuity_are_not_clean(self):
        last = row(1)
        last["utc"] = row(9)["utc"]
        result = assess([row(0), last], None, None)
        self.assertIn("POWER_PLAN_UNKNOWN_OR_CHANGED", result["reasons"])
        self.assertIn("HOST_SAMPLING_GAP_OR_CLOCK_DISCONTINUITY", result["reasons"])

    def test_preflight_battery_blocks_and_preserves_report(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = HostMonitor(
                Path(folder),
                sampler=Mock(side_effect=[row(0, False), row(1, False)]),
                plan_reader=lambda: "same",
            )
            with self.assertRaisesRegex(RuntimeError, "HOST_AC_OR_POWER_PLAN_UNAVAILABLE"):
                monitor.start()
            result = monitor.close()
            self.assertFalse(result["valid"])
            self.assertIsNone(monitor.thread)
            self.assertTrue((Path(folder) / "host-review.json").exists())

    def test_monitor_exports_and_closes_before_returning(self):
        with tempfile.TemporaryDirectory() as folder:
            monitor = HostMonitor(
                Path(folder),
                sampler=Mock(side_effect=[row(0), row(1)]),
                plan_reader=lambda: "same",
                interval=3600,
            )
            monitor.start()
            result = monitor.close()
            self.assertTrue(result["valid"])
            self.assertFalse(monitor.thread.is_alive())
            saved = json.loads((Path(folder) / "host-review.json").read_text())
            self.assertEqual(saved["samples"], 2)

    def test_controlled_mode_cannot_silently_use_old_observer(self):
        with self.assertRaisesRegex(RuntimeError, "CONTROLLED_REFERENCE_REQUIRES_REUSE_DIAGNOSTIC"):
            _execute(None, None, diagnostic=True, controlled_host=True)


class MemoryGuardTests(unittest.TestCase):
    def test_low_memory_is_sticky_and_phase_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            low = {**row(0), "host_available_bytes": 1 * 2**30}
            recovered = {**row(1), "host_available_bytes": 4 * 2**30}
            monitor = HostMonitor(Path(folder), sampler=lambda: recovered)
            monitor.rows = [low]
            with self.assertRaisesRegex(RuntimeError, "HOST_MEMORY_BELOW_GUARD"):
                monitor.require_safe("before_offer")
            saved = json.loads((Path(folder) / "host-phases.jsonl").read_text())
            self.assertEqual(saved["phase"], "before_offer")
            self.assertFalse(saved["safe"])

    def test_unknown_memory_or_stale_monitor_never_passes(self):
        for previous, current, reason in [
            (row(0), row(1), "MEMORY_UNAVAILABLE"),
            (
                {**row(0), "host_available_bytes": 4 * 2**30},
                {**row(8), "host_available_bytes": 4 * 2**30},
                "MONITOR_STALE",
            ),
        ]:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as folder:
                monitor = HostMonitor(Path(folder), sampler=lambda: current)
                monitor.rows = [previous]
                with self.assertRaisesRegex(RuntimeError, reason):
                    monitor.require_safe("post_load")

    def test_same_safe_phase_does_not_grow_journal_each_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            current = {**row(1), "host_available_bytes": 4 * 2**30}
            monitor = HostMonitor(Path(folder), sampler=lambda: current)
            monitor.rows = [{**row(0), "host_available_bytes": 4 * 2**30}]
            monitor.require_safe("load_observation")
            monitor.require_safe("load_observation")
            self.assertEqual(len((Path(folder) / "host-phases.jsonl").read_text().splitlines()), 1)
