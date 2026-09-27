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


class ThrottlingStartupTests(unittest.TestCase):
    def run_wait(self, folder, outcomes, seconds=10):
        from pathlib import Path

        from scripts.scale_diagnostic import wait_throttling

        clock = [0.0]

        def sleep(duration):
            clock[0] += duration

        sampler = Mock(side_effect=outcomes)
        result = wait_throttling(
            None,
            Path(folder) / "startup.jsonl",
            seconds=seconds,
            sample=sampler,
            monotonic=lambda: clock[0],
            sleep=sleep,
        )
        return result, sampler

    def test_missing_startup_metric_is_retried_and_preserved(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            value = {"counters": [{"value": 0}]}
            result, sampler = self.run_wait(
                folder, [RuntimeError("THROTTLING_METRIC_UNAVAILABLE_notifications"), value]
            )
            self.assertIs(result, value)
            self.assertEqual(sampler.call_count, 2)
            journal = [
                json.loads(x) for x in (Path(folder) / "startup.jsonl").read_text().splitlines()
            ]
            self.assertEqual([x["available"] for x in journal], [False, True])
            self.assertEqual(journal[-1]["elapsed_seconds"], 5)

    def test_persistent_absence_reaches_bounded_timeout(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, "THROTTLING_PREFLIGHT_TIMEOUT"):
                self.run_wait(folder, RuntimeError("THROTTLING_METRIC_UNAVAILABLE_notifications"))
            rows = (Path(folder) / "startup.jsonl").read_text().splitlines()
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(not json.loads(x)["available"] for x in rows))

    def test_invalid_counter_and_command_failure_are_not_retried(self):
        import tempfile

        for code in ("INVALID_THROTTLING_COUNTER", "COMMAND_FAILED_KUBECTL"):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(RuntimeError, code):
                    self.run_wait(folder, [RuntimeError(code), {"should_not_be_used": True}])


class CharacterizationSettingsTests(unittest.TestCase):
    def test_bounded_profiles_preserve_baseline_and_other_settings(self):
        from scripts.scale_contract import schedule
        from scripts.scale_diagnostic import characterization_settings

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ],
            "replicas": [1, 2],
            "http_concurrency": 8,
        }
        for rate, total in [(8, 300), (12, 420), (16, 540)]:
            result = characterization_settings(
                base, rate, diagnostic=True, reuse=True, controlled=True, extension=None
            )
            self.assertEqual(
                len(
                    schedule(
                        result["stages"],
                        characterization=result.get("capacity_characterization", False),
                    )
                ),
                total,
            )
            self.assertEqual(result["http_concurrency"], 8)
        self.assertEqual(base["stages"][1]["rate"], 8)
        self.assertEqual(base["replicas"], [1, 2])

    def test_rejects_uncontrolled_or_adaptive_characterization(self):
        from scripts.scale_diagnostic import characterization_settings

        good = dict(diagnostic=True, reuse=True, controlled=True, extension=None)
        for key, value in [
            ("diagnostic", False),
            ("reuse", False),
            ("controlled", False),
            ("extension", object()),
        ]:
            with self.subTest(key=key), self.assertRaisesRegex(RuntimeError, "REQUIRES_CONTROLLED"):
                characterization_settings({}, 12, **{**good, key: value})
        with self.assertRaisesRegex(RuntimeError, "RATE_NOT_ALLOWED"):
            characterization_settings({}, 20, **good)
        with self.assertRaisesRegex(RuntimeError, "BASELINE_CHANGED"):
            characterization_settings({"stages": []}, 12, **good)

    def test_historical_schedule_limit_remains_and_new_profile_is_exact(self):
        from scripts.scale_contract import schedule

        stages = [
            {"seconds": 15, "rate": 2},
            {"seconds": 30, "rate": 12},
            {"seconds": 15, "rate": 2},
        ]
        with self.assertRaisesRegex(ValueError, "STAGE_LIMIT"):
            schedule(stages)
        with self.assertRaisesRegex(ValueError, "CHARACTERIZATION_PROFILE_NOT_ALLOWED"):
            schedule([{"seconds": 60, "rate": 16}], characterization=True)

    def test_admission_override_changes_only_concurrency(self):
        from scripts.scale_diagnostic import characterization_settings

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ],
            "replicas": [1, 2],
            "http_concurrency": 8,
        }
        flags = dict(diagnostic=True, reuse=True, controlled=True, extension=None)
        before = characterization_settings(base, 12, **flags)
        after = characterization_settings(base, 12, http_concurrency=16, **flags)
        self.assertEqual(after, {**before, "http_concurrency": 16})
        self.assertEqual(base["http_concurrency"], 8)
        for rate in (12, 16):
            before = characterization_settings(base, rate, **flags)
            after = characterization_settings(base, rate, http_concurrency=16, **flags)
            self.assertEqual(after, {**before, "http_concurrency": 16})
            for flag in ("diagnostic", "reuse", "controlled"):
                with (
                    self.subTest(rate=rate, flag=flag),
                    self.assertRaisesRegex(RuntimeError, "REQUIRES_CONTROLLED"),
                ):
                    characterization_settings(
                        base, rate, http_concurrency=16, **{**flags, flag: False}
                    )
        for rate, concurrency in [(8, 16), (12, 32), (16, 32)]:
            with (
                self.subTest(rate=rate, concurrency=concurrency),
                self.assertRaisesRegex(RuntimeError, "ADMISSION_CONCURRENCY_PROFILE_NOT_ALLOWED"),
            ):
                characterization_settings(base, rate, http_concurrency=concurrency, **flags)

    def test_two_replicas_require_exact_bounded_profile_and_controlled_host(self):
        from scripts.scale_contract import schedule
        from scripts.scale_diagnostic import characterization_settings

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ],
            "replicas": [1, 2],
            "http_concurrency": 8,
        }
        flags = dict(
            diagnostic=True,
            reuse=True,
            controlled=True,
            extension=None,
            http_concurrency=16,
            fixed_replicas=2,
        )
        two = characterization_settings(base, 16, **flags)
        one = characterization_settings(base, 16, **{**flags, "fixed_replicas": 1})
        self.assertEqual(two, {**one, "replicas": [2]})
        self.assertEqual(len(schedule(two["stages"], characterization=True)), 540)
        for rate, override in [
            (12, {}),
            (16, {"http_concurrency": 8}),
            (16, {"plateau_seconds": 45}),
            (16, {"controlled": False}),
            (16, {"extension": object()}),
            (16, {"fixed_replicas": 3}),
        ]:
            with self.subTest(rate=rate, override=override), self.assertRaises(RuntimeError):
                characterization_settings(base, rate, **{**flags, **override})


class ExtendedPlateauTests(unittest.TestCase):
    def test_only_duration_changes_and_exact_600_event_limit(self):
        from scripts.scale_contract import schedule
        from scripts.scale_diagnostic import characterization_settings

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ],
            "replicas": [1, 2],
            "http_concurrency": 8,
        }
        flags = dict(
            diagnostic=True, reuse=True, controlled=True, extension=None, http_concurrency=16
        )
        old = characterization_settings(base, 12, **flags)
        new = characterization_settings(base, 12, plateau_seconds=45, **flags)
        self.assertEqual(len(schedule(new["stages"], characterization=True)), 600)
        self.assertEqual(base["stages"][1]["seconds"], 30)
        new["stages"][1]["seconds"] = 30
        self.assertEqual(old, new)
        for rate, duration, concurrency in [
            (8, 45, 8),
            (16, 45, 8),
            (16, 45, 16),
            (12, 45, 8),
            (12, 60, 16),
        ]:
            with (
                self.subTest(rate=rate, duration=duration, concurrency=concurrency),
                self.assertRaisesRegex(RuntimeError, "DURATION_NOT_ALLOWED"),
            ):
                characterization_settings(
                    base,
                    rate,
                    plateau_seconds=duration,
                    **{**flags, "http_concurrency": concurrency},
                )
        with self.assertRaises(ValueError):
            schedule(
                [
                    {"seconds": 15, "rate": 2},
                    {"seconds": 46, "rate": 12},
                    {"seconds": 15, "rate": 2},
                ],
                characterization=True,
            )


class ResponseMetadataTests(unittest.TestCase):
    def response(self, body, status=503, **headers):
        return SimpleNamespace(
            status=status,
            body=body,
            headers={"Content-Type": "application/problem+json", **headers},
        )

    def test_correlates_existing_response_without_retries_or_sensitive_fields(self):
        uid = "12345678-1234-4567-89ab-123456789abc"
        response = self.response(
            json.dumps(
                {
                    "status": 503,
                    "code": "SERVICE_UNAVAILABLE",
                    "request_id": uid,
                    "detail": "private-secret",
                    "errors": ["private-secret"],
                }
            ).encode(),
            **{"X-Request-ID": uid},
        )
        inner = Mock(return_value=response)
        transport = TimedTransport(inner)
        self.assertIs(
            transport(
                "GET",
                "http://localhost/api/v1/carrier-events/private-inbox",
                {"X-Request-ID": uid, "Authorization": "private-secret"},
                None,
                2,
            ),
            response,
        )
        inner.assert_called_once()
        row = transport.records[0]
        self.assertEqual(row["sent_request_id"], uid)
        self.assertEqual(row["response_request_id"], uid)
        self.assertEqual(row["problem_request_id"], uid)
        self.assertEqual(row["problem_code"], "SERVICE_UNAVAILABLE")
        self.assertNotIn("private", json.dumps(row))

    def test_bad_or_unexpected_error_metadata_does_not_mask_original_status(self):
        cases = [
            b"not-json",
            b"[]",
            b'{"status":500,"code":"SERVICE_UNAVAILABLE"}',
            b'{"status":503,"code":["private-secret"]}',
            b'{"status":503,"code":"private-secret","request_id":"private-secret"}',
            b"x" * 4097,
            b"[" * 2000 + b"]" * 2000,
        ]
        for body in cases:
            with self.subTest(body=body[:20]):
                response = self.response(body, **{"X-Request-ID": "private-secret"})
                transport = TimedTransport(Mock(return_value=response))
                self.assertIs(
                    transport("GET", "http://localhost/api/v1/orders/id", {}, None, 2), response
                )
                row = transport.records[0]
                self.assertEqual(row["http_status"], 503)
                self.assertNotIn("problem_code", row)
                self.assertNotIn("private-secret", json.dumps(row))

    def test_success_body_is_not_inspected_and_ids_are_not_conflated(self):
        sent = "12345678-1234-4567-89ab-123456789abc"
        received = "12345678-1234-4567-89ab-123456789abd"
        response = self.response(b"private-secret", status=200, **{"X-Request-ID": received})
        transport = TimedTransport(Mock(return_value=response))
        transport("GET", "http://localhost/api/v1/orders/id", {"X-Request-ID": sent}, None, 2)
        row = transport.records[0]
        self.assertEqual(row["sent_request_id"], sent)
        self.assertEqual(row["response_request_id"], received)
        self.assertNotIn("problem_metadata_state", row)
        self.assertNotIn("private-secret", json.dumps(row))

    def test_http_duration_ends_before_metadata_extraction(self):
        response = self.response(b"{}")
        transport = TimedTransport(Mock(return_value=response))
        with (
            patch("scripts.scale_diagnostic.time.monotonic", side_effect=[10, 11]),
            patch("scripts.scale_diagnostic.diagnostic_metadata", return_value={}) as metadata,
        ):
            transport("GET", "http://localhost/api/v1/orders/id", {}, None, 2)
        metadata.assert_called_once()
        self.assertEqual(transport.records[0]["duration_seconds"], 1)


class DiagnosticReviewReplicaTests(unittest.TestCase):
    def test_review_uses_recorded_replica_directory_and_verifies_its_hashes(self):
        import hashlib
        import tempfile
        from pathlib import Path

        from scripts.review_scale_diagnostic import review

        for replicas in (1, 2, None):
            with self.subTest(replicas=replicas), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                name = "adaptive" if replicas is None else f"fixed-{replicas}"
                folder = root / name
                folder.mkdir()
                data = {
                    "protocol.json": {
                        "diagnostic": {
                            "fixed_replicas": replicas,
                            "enabled": True,
                            "condition": "adaptive" if replicas is None else "fixed",
                        }
                    },
                    "summary.json": {"complete": True},
                    f"{name}/summary.json": {"initial_fixed_replicas": replicas},
                    f"{name}/events.json": [],
                    f"{name}/series.jsonl": {
                        "monotonic": 1,
                        "collection_end_monotonic": 2,
                        "interval_overrun_seconds": 0,
                        "inbox": {"eligible": 0, "oldest_eligible_seconds": 0},
                        "throttling": {
                            "counters": [],
                            "request_start_monotonic": 1,
                            "request_end_monotonic": 2,
                        },
                    },
                }
                for name, value in data.items():
                    (root / name).write_text(json.dumps(value), encoding="utf-8")
                (root / "checksums.sha256").write_text(
                    "\n".join(
                        hashlib.sha256((root / name).read_bytes()).hexdigest() + "  " + name
                        for name in data
                    ),
                    encoding="utf-8",
                )
                result = review(root)
                self.assertEqual(result["functional"]["initial_fixed_replicas"], replicas)
                self.assertEqual(result["verified_files"], len(data))
                (folder / "events.json").write_text("[{}]", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "CHECKSUM_MISMATCH"):
                    review(root)


class ResultDimensionsTests(unittest.TestCase):
    def test_missing_offer_does_not_erase_completed_accepted_work(self):
        from scripts.scale_calibration import result_dimensions

        final = [
            {"acceptance": {"status": 202}, "classification": "completed_in_time"},
            {"acceptance": None, "classification": "not_offered"},
        ]
        result = result_dimensions(
            final, {"completed_in_time": 1, "not_offered": 1}, {"complete": True}
        )
        self.assertFalse(result["offer_complete"])
        self.assertTrue(result["accepted_completed_in_time"])
        self.assertTrue(result["post_observation_eligible"])
        self.assertEqual(result["accepted_events"], 1)

    def test_unknown_acceptance_or_no_accepted_work_cannot_continue(self):
        from scripts.scale_calibration import result_dimensions

        for status, acceptance in [
            ("acceptance_unknown", None),
            ("not_offered", None),
        ]:
            result = result_dimensions(
                [{"acceptance": acceptance, "classification": status}],
                {status: 1},
                {"complete": True},
            )
            self.assertFalse(result["post_observation_eligible"])

    def test_late_completion_is_a_result_not_a_host_safety_failure(self):
        from scripts.scale_calibration import result_dimensions

        result = result_dimensions(
            [{"acceptance": {"status": 202}, "classification": "completed_late"}],
            {"completed_late": 1},
            {"complete": True},
        )
        self.assertFalse(result["accepted_completed_in_time"])
        self.assertTrue(result["post_observation_eligible"])
