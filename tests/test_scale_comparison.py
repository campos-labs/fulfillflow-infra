"""Comparison validity, sampled capacity and isolation; no live workload."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import scale_comparison as cmp
from scripts.scale_calibration import observe
from scripts.scale_contract import cluster_name


class ComparisonTests(unittest.TestCase):
    def test_cluster_is_opt_in_and_invalid_selector_refused(self):
        self.assertEqual(cluster_name(""), "fulfillflow-scale-01")
        self.assertEqual(cluster_name("comparison-v1"), "fulfillflow-scale-compare-01")
        with self.assertRaises(RuntimeError):
            cluster_name("anything")
        with self.assertRaisesRegex(RuntimeError, "COMPARISON_CLUSTER_REQUIRED"):
            cmp.require_context()

    def test_three_blocks_balance_every_position(self):
        blocks = cmp.order(cmp.config()["seed"])
        self.assertEqual(blocks, cmp.order(cmp.config()["seed"]))
        for block in blocks:
            self.assertEqual(set(block), set(cmp.CONDITIONS))
        for position in range(3):
            self.assertEqual({b[position] for b in blocks}, set(cmp.CONDITIONS))

    def test_formal_settings_do_not_change_pilot_defaults(self):
        from scripts.scale_keda import Pilot

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ]
        }
        self.assertEqual(
            Pilot(capacity_profile=True).capacity_settings(base)["http_concurrency"], 16
        )
        for name in cmp.CONDITIONS:
            trial = cmp.Trial(name)
            s = trial.capacity_settings(base)
            self.assertEqual(s["http_concurrency"], 32)
            self.assertEqual(s["stages"][1], {"seconds": 60, "rate": 16})
            self.assertEqual(s["replicas"], [2 if name == "fixed-2" else 1])
        self.assertEqual(base["stages"][1]["rate"], 8)

    def test_fixed_controller_bounds_only_change_replica_range(self):
        from scripts.scale_keda import scaled_object

        for condition, n in [("fixed-1", 1), ("fixed-2", 2), ("adaptive", None)]:
            pilot = cmp.Trial(condition)
            with (
                patch.object(cmp, "get", side_effect=[None, {"metadata": {"uid": "owned"}}]),
                patch.object(cmp, "k", return_value='{"items":[]}'),
                patch.object(cmp, "apply") as apply,
            ):
                pilot.activate(Path("unused"))
            obj = apply.call_args.args[1]
            expected = scaled_object(pilot.pin)
            if n:
                expected["spec"]["minReplicaCount"] = n
                expected["spec"]["maxReplicaCount"] = n
            self.assertEqual(obj, expected)

    @staticmethod
    def sample(t, n, terminating=False):
        return {
            "pod_inventory": {
                "observed_monotonic": t,
                "pods": [
                    {
                        "uid": str(i),
                        "phase": "Running",
                        "ready": not terminating,
                        "deleting_at": "now" if terminating else None,
                    }
                    for i in range(n)
                ],
            }
        }

    def test_pod_time_clips_common_window_and_keeps_terminating(self):
        s = [self.sample(-1, 1), self.sample(4, 2), self.sample(9, 2, True), self.sample(14, 1)]
        r = cmp.pod_time(s, 0, 12)
        self.assertEqual(r["existing_pod_seconds"], 20)
        self.assertEqual(r["ready_pod_seconds"], 14)
        self.assertEqual(r["terminating_pod_seconds"], 6)

    def test_pod_time_rejects_missing_boundaries_and_gaps(self):
        for times in ([1, 5, 10], [0, 5, 9], [0, 11, 15], [0, 5, 5, 10]):
            with self.subTest(times=times), self.assertRaises(RuntimeError):
                cmp.pod_time([self.sample(t, 1) for t in times], 0, 10)

    def fixture(self, classification="completed_in_time"):
        events = [
            {
                "classification": classification,
                "acceptance": {"request_id": str(i), "inbox_id": "id"},
            }
            for i in range(1020)
        ]
        records = (
            [{"request_id": str(i)} for i in range(1020)]
            if classification.startswith("completed")
            else []
        )
        attribution = {"records": records, "log_gaps": [], "pods": [], "restart_baseline": {}}
        return (
            events,
            [{"kind": "load_finished"}],
            attribution,
            [{"controller": {"metric": {"available": True}}}],
        )

    def test_late_pending_business_failure_and_unknown_are_outcomes(self):
        for classification in (
            "completed_late",
            "pending_at_end",
            "business_failed",
            "inconclusive",
        ):
            result = cmp.judge(*self.fixture(classification))
            self.assertTrue(result["execution_valid"], classification)
            self.assertEqual(result["confirmed_in_time_fraction"], 0)

    def test_missing_offer_is_invalid_even_with_other_successes(self):
        args = self.fixture()
        args[0][0] = {"classification": "not_offered", "acceptance": None}
        result = cmp.judge(*args)
        self.assertFalse(result["execution_valid"])
        self.assertEqual(result["confirmed_in_time_fraction"], 1)

    def test_missing_logs_for_completed_or_unavailable_metric_invalidates(self):
        args = self.fixture()
        args[2]["records"].pop()
        self.assertIn("ATTRIBUTION_MISMATCH", cmp.judge(*args)["invalid_reasons"])
        args = self.fixture()
        args[3][0]["controller"]["metric"]["available"] = False
        self.assertIn("METRIC_UNAVAILABLE", cmp.judge(*args)["invalid_reasons"])

    def test_restore_checks_identity_before_any_mutation(self):
        with (
            patch.object(cmp, "baseline", side_effect=RuntimeError("BASELINE_IDENTITY")),
            patch.object(cmp, "runtime") as runtime,
            patch.object(cmp, "sql") as sql,
        ):
            with self.assertRaises(RuntimeError):
                cmp.restore(Path("unused"), Path("unused"))
            runtime.assert_not_called()
            sql.assert_not_called()

    def test_nonempty_broker_blocks_restore_without_purge(self):
        with (
            patch.object(cmp, "baseline", return_value={}),
            patch.object(cmp, "get", return_value=None),
            patch.object(cmp.env, "kubectl", return_value='{"items":[]}'),
            patch.object(cmp, "runtime"),
            patch.object(cmp, "queues", return_value=[{"name": "pending", "messages": 1}]),
            patch.object(cmp, "sql") as sql,
        ):
            with self.assertRaisesRegex(RuntimeError, "PENDING_BROKER"):
                cmp.restore(Path("unused"), Path("unused"))
            sql.assert_not_called()

    def test_baseline_hash_rechecked_before_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / "baseline").mkdir()
            hashes = {}
            for owner in cmp.OWNERS:
                (p / "baseline" / f"{owner}.sql").write_text("baseline")
                hashes[owner] = cmp.digest(p / "baseline" / f"{owner}.sql")
            (p / "comparison-baseline.json").write_text(
                json.dumps(
                    {
                        "identity": {"container_id": "campaign"},
                        "protocol_sha256": cmp.digest(cmp.CONFIG),
                        "hashes": hashes,
                        "templates": {},
                    }
                )
            )
            with (
                patch.object(cmp, "assert_owned", return_value={"container_id": "campaign"}),
                patch.object(cmp, "template_hashes", return_value={}),
            ):
                cmp.baseline(p)
                (p / "baseline/core.sql").write_text("changed")
                with self.assertRaisesRegex(RuntimeError, "BASELINE_HASH"):
                    cmp.baseline(p)

    def test_expired_observer_does_not_issue_http_or_overwrite_pending(self):
        verifier = Mock()
        with patch("scripts.scale_calibration.time.monotonic", return_value=121):
            result = observe(verifier, {"event_id": "e", "observation_deadline": 120})
        self.assertTrue(result["observation_expired"])
        verifier.get.assert_not_called()


class CommonWindowTests(unittest.TestCase):
    def test_completed_events_do_not_shorten_common_window(self):
        from scripts import scale_calibration as cal
        from scripts.scale_contract import metric

        class Clock:
            now = 0.0

            def sleep(self, n):
                self.now += n

            def monotonic(self):
                return self.now

        clock = Clock()
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "measurement"

            def start_child(*args, **kwargs):
                item = json.loads((folder / "prepared.json").read_text())[0]
                records = [
                    {"kind": "dispatch_attempt", "scheduled_monotonic": 0},
                    {"kind": "offered", "event_id": item["event_id"], "monotonic": 0},
                    {
                        "kind": "response",
                        "event_id": item["event_id"],
                        "status": 202,
                        "monotonic": 0.01,
                        "inbox_id": "inbox",
                        "request_id": "request",
                    },
                    {"kind": "load_finished"},
                ]
                (folder / "admission.jsonl").write_text(
                    "".join(json.dumps(x) + "\n" for x in records)
                )
                child = Mock()
                child.poll.return_value = 0
                child.returncode = 0
                return child

            zero = metric(
                {
                    "eligible": 0,
                    "waiting_retry": 0,
                    "blocked": 0,
                    "done": 1,
                    "oldest_eligible_seconds": 0,
                }
            )
            collector = Mock()
            collector.failed.is_set.return_value = False
            policy = Mock()
            policy.sample.side_effect = lambda private, sample: sample
            policy.attribution.return_value = {"complete": True, "per_pod": {"pod": 1}}
            settings = {
                "formal_comparison": True,
                "stages": [{"seconds": 1, "rate": 1}],
                "http_concurrency": 32,
                "functional_deadline_seconds": 60,
                "observation_seconds": 120,
                "collection_interval_seconds": 5,
            }
            with (
                patch.object(cal.time, "monotonic", clock.monotonic),
                patch.object(cal.time, "sleep", clock.sleep),
                patch.object(cal.environment, "kubectl"),
                patch.object(cal, "verify_images"),
                patch.object(cal, "db_metric", return_value=zero),
                patch.object(cal.telemetry, "wait_worker_count", return_value=[]),
                patch.object(cal.telemetry, "Collector", return_value=collector),
                patch.object(cal.telemetry, "temporal_sample", return_value={}),
                patch("scripts.scale_diagnostic.throttling_sample", return_value={}),
                patch.object(cal.Verifier, "prepare", return_value=("order", "shipment", "code")),
                patch.object(cal.subprocess, "Popen", side_effect=start_child),
                patch.object(
                    cal,
                    "observe",
                    side_effect=lambda v, item, **kw: {
                        "event_id": item["event_id"],
                        "completed_monotonic": 1,
                    },
                ) as observe,
            ):
                result = cal.run_one(
                    Path(tmp),
                    folder,
                    1,
                    settings,
                    {"observer": "test", "alpha": "test"},
                    "http://127.0.0.1:18181",
                    {},
                    1000,
                    policy=policy,
                    diagnostic=True,
                    reuse_terminal_reads=True,
                )
            self.assertTrue(result)
            self.assertEqual(clock.now, 450)
            self.assertEqual(observe.call_count, 1)
            self.assertEqual(
                json.loads((folder / "window.json").read_text()),
                {"start": 0, "end": 450, "seconds": 450},
            )


if __name__ == "__main__":
    unittest.main()
