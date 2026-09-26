"""Checks for retrospective aggregation, not live Kubernetes."""

import unittest

from scripts.review_scale_pilot import cpu_reads, plateau_rows


class ReviewTests(unittest.TestCase):
    def test_repeated_source_timestamp_is_not_an_independent_cpu_reading(self):
        pod = {"pod": "core-api", "uid": "one", "cpu": {"time": "t1", "usageNanoCores": 500000000}}
        samples = [{"resources": [pod]}, {"resources": [pod]}]
        result = cpu_reads(samples, "core-")
        self.assertEqual((result["collected"], result["distinct"], result["near_500m"]), (2, 1, 1))
        samples.append({"resources": [{**pod, "uid": "another"}]})
        self.assertEqual(cpu_reads(samples, "core-")["distinct"], 2)

    def test_counter_interval_crossing_phase_boundary_is_flagged(self):
        series = [
            {"inbox_observed_monotonic": t, "inbox": {"done": n}}
            for t, n in [(12, 0), (17, 20), (22, 60)]
        ]
        rows = plateau_rows(series, 0)
        self.assertFalse(rows[0]["interval_fully_in_plateau"])
        self.assertTrue(rows[1]["interval_fully_in_plateau"])
        self.assertEqual(rows[1]["done_per_second"], 8)

    def test_counter_reset_cannot_be_reported_as_throughput(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COUNTER_INTERVAL"):
            plateau_rows(
                [
                    {"inbox_observed_monotonic": t, "inbox": {"done": n}}
                    for t, n in [(17, 20), (22, 0)]
                ],
                0,
            )
