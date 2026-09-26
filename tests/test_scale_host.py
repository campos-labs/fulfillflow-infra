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
