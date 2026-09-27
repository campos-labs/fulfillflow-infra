"""Sampling independence, failure visibility, and workload attribution contracts."""

import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from scripts.scale_contract import dispatch_diagnostic
from scripts.scale_observation import Collector, matching_records, wait_worker_count


class ObservationTests(unittest.TestCase):
    def test_scale_down_waits_for_old_pod_to_disappear(self):
        with (
            patch(
                "scripts.scale_observation.worker_pods",
                side_effect=[[{"uid": "a"}, {"uid": "b"}], [{"uid": "a"}]],
            ) as query,
            patch("scripts.scale_observation.time.sleep"),
        ):
            self.assertEqual(wait_worker_count(Path("unused"), 1), [{"uid": "a"}])
        self.assertEqual(query.call_count, 2)

    def test_dispatch_records_both_independent_limits(self):
        item = dispatch_diagnostic(10, 10.4, 8, 8)
        self.assertEqual(item["reasons"], ["client_concurrency_limit", "scheduler_lag"])
        self.assertEqual(dispatch_diagnostic(10, 10.1, 7, 8)["reasons"], [])
        self.assertEqual(dispatch_diagnostic(10, 10.4, 0, 8)["reasons"], ["scheduler_lag"])
        self.assertEqual(
            dispatch_diagnostic(10, 10.1, 8, 8)["reasons"], ["client_concurrency_limit"]
        )

    def test_collector_continues_without_observer_iteration(self):
        with TemporaryDirectory() as folder:
            second = threading.Event()
            calls = []

            def sample():
                calls.append(1)
                if len(calls) > 1:
                    second.set()
                return {"sample": len(calls)}

            collector = Collector(Path(folder) / "series.jsonl", sample, 0.01)
            try:
                collector.start()
                self.assertTrue(second.wait(2))
            finally:
                collector.close()
            self.assertFalse(collector.thread.is_alive())

    def test_failed_metric_is_reported_not_replaced_with_zero(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "series.jsonl"

            def sample():
                raise ValueError("bad metric")

            collector = Collector(path, sample, 5)
            with self.assertRaisesRegex(RuntimeError, "COLLECTION_START_FAILED"):
                collector.start()
            self.assertTrue(
                json.loads(path.with_suffix(".error.json").read_text())["metric_unknown"]
            )
            self.assertEqual(path.read_text(), "")

    def test_attribution_selects_only_committed_processing_for_this_cohort(self):
        done = {
            "service": "core",
            "stage": "process",
            "outcome": "DONE",
            "request_id": "ours",
            "secret": "must not export",
        }
        text = "\n".join(
            json.dumps(row)
            for row in [
                done,
                {**done, "request_id": "old"},
                {**done, "stage": "receive"},
                {**done, "outcome": "RETRY_WAIT"},
            ]
        )
        selected = matching_records(text, {"ours"})
        self.assertEqual(len(selected), 1)
        self.assertNotIn("secret", selected[0])
