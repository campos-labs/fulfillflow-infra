"""Diagnostic instrumentation must preserve errors, identities and secret boundaries."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.scale_diagnostic import (
    CONTAINERS,
    METRICS,
    TimedTransport,
    parse_throttling,
    require_fixed_target,
)


def exposition():
    return "\n".join(
        f'{metric}{{namespace="fulfillflow",container="{container}",pod="{container}-pod",id="/{container}/instance"}} 2 123456'
        for container in CONTAINERS
        for metric in METRICS
    )


class DiagnosticTests(unittest.TestCase):
    def test_container_metrics_exclude_pod_aggregates_and_keep_source_time(self):
        text = (
            exposition()
            + '\ncontainer_cpu_cfs_periods_total{namespace="fulfillflow",container="",pod="core-pod",id="/pod"} 999 123456'
        )
        rows = parse_throttling(text)
        self.assertEqual(len(rows), 18)
        self.assertEqual(rows[0]["source_timestamp_ms"], 123456)
        self.assertTrue(all(r["value"] == 2 for r in rows))

    def test_missing_counter_or_timestamp_is_not_zero(self):
        for text in (
            "",
            exposition().replace(" 2 123456", " 2"),
            "\n".join(exposition().splitlines()[1:]),
        ):
            with self.assertRaisesRegex(RuntimeError, "THROTTLING_METRIC_UNAVAILABLE"):
                parse_throttling(text)

    def test_invalid_counter_is_rejected(self):
        for value in ("NaN", "Inf", "-1"):
            with self.assertRaisesRegex(RuntimeError, "INVALID_THROTTLING_COUNTER"):
                parse_throttling(exposition().replace(" 2 ", " " + value + " "))

    def test_timing_does_not_change_response_or_leak_request(self):
        response = SimpleNamespace(status=200)
        original = Mock(return_value=response)
        transport = TimedTransport(original)
        headers, body = {"Authorization": "secret-token"}, b"private-body"
        url = "http://localhost/api/v1/orders/private-id?secret=query"
        self.assertIs(transport("GET", url, headers, body, 4), response)
        original.assert_called_once_with("GET", url, headers, body, 4)
        record = transport.records[0]
        self.assertEqual(record["endpoint"], "orders")
        self.assertGreaterEqual(record["duration_seconds"], 0)
        for value in ("private", "secret", "localhost"):
            self.assertNotIn(value, json.dumps(record))

    def test_failure_is_recorded_and_reraised_without_detail(self):
        error = RuntimeError("private-secret")
        transport = TimedTransport(Mock(side_effect=error))
        with self.assertRaises(RuntimeError) as raised:
            transport("GET", "http://localhost/api/v1/orders/one", {}, None, 1)
        self.assertIs(raised.exception, error)
        self.assertIsNone(transport.records[0]["http_status"])
        self.assertEqual(transport.records[0]["error"], "RuntimeError")
        self.assertNotIn("private-secret", json.dumps(transport.records))

    @patch("scripts.scale_diagnostic.env.kubectl")
    def test_refuses_controller_without_deleting_it(self, command):
        command.return_value = json.dumps(
            {"items": [{"spec": {"scaleTargetRef": {"name": "core-worker"}}}]}
        )
        with self.assertRaisesRegex(RuntimeError, "DIAGNOSTIC_TARGET_HAS_HPA"):
            require_fixed_target(None)
        self.assertEqual(command.call_count, 1)


class CounterWindowTests(unittest.TestCase):
    def series(self, amounts):
        return [
            {
                "throttling": {
                    "counters": [
                        {
                            "container": "core",
                            "pod": "core-one",
                            "id": "/one",
                            "metric": m,
                            "source_timestamp_ms": t,
                            "value": value,
                        }
                        for m in METRICS
                    ]
                }
            }
            for t, value in amounts
        ]

    def test_repeated_source_values_do_not_inflate_deltas(self):
        from scripts.review_scale_diagnostic import windows

        row = windows(self.series([(1000, 2), (1000, 2), (2000, 5)]))[0]
        self.assertEqual(row["periods"], 3)
        self.assertEqual(row["distinct_timestamps"], 2)
        self.assertEqual(row["window_seconds"], 1)

    def test_reset_and_single_timestamp_are_unknown(self):
        from scripts.review_scale_diagnostic import windows

        for values in ([(1000, 5), (2000, 2)], [(1000, 5), (1000, 5)]):
            row = windows(self.series(values))[0]
            self.assertFalse(row["valid"])
            self.assertNotIn("throttled_period_fraction", row)

    def test_conflicting_value_same_source_timestamp_is_rejected(self):
        from scripts.review_scale_diagnostic import windows

        with self.assertRaisesRegex(ValueError, "CONFLICTING_SOURCE_TIMESTAMP"):
            windows(self.series([(1000, 2), (1000, 3)]))
