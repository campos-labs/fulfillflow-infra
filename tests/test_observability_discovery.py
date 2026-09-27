"""Correlation must reject false joins and preserve uncertainty, clocks and source files."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import observability_discovery as discovery


def fixture():
    prepared = {"event_id": "external", "order_id": "order", "shipment_id": "shipment"}
    acceptance = {
        "event_id": "external",
        "kind": "response",
        "status": 202,
        "request_id": "admission-request",
        "inbox_id": "inbox",
        "utc": "2026-09-27T00:00:00+00:00",
        "monotonic": 12,
    }
    event = {
        **prepared,
        "acceptance": acceptance,
        "tracking_event_id": "business-event",
        "notification_id": "notification",
        "classification": "completed_late",
        "completed_monotonic": 80,
    }
    worker = {
        "request_id": "admission-request",
        "event_id": "business-event",
        "outcome": "DONE",
        "duration_ms": 9,
        "timestamp": "2026-09-27T00:00:01+00:00",
        "message_id": "message",
        "body": "must not be exported",
    }
    observations = [
        {"phase": "order_created", "order_id": "order"},
        {"phase": "shipment_created", "shipment_id": "shipment"},
        {"phase": "tracking_completed", "tracking_event_id": "business-event"},
        {"phase": "business_completed"},
        {
            "phase": "notifications_simulated",
            "tracking_event_id": "business-event",
            "notification_id": "notification",
        },
    ]
    query = {
        "method": "GET",
        "start_monotonic": 20,
        "end_monotonic": 21,
        "http_status": 200,
        "sent_request_id": "query-request",
        "response_request_id": "query-request",
        "authorization": "must not be exported",
    }
    return [prepared, event, [acceptance.copy()], [worker], observations, [query]]


class DiscoveryTests(unittest.TestCase):
    def test_distinct_business_and_http_ids_correlate_without_synthetic_trace(self):
        inputs = fixture()
        before = copy.deepcopy(inputs)
        result = discovery.correlate(*inputs)
        self.assertEqual(result["external_event_id"], "external")
        self.assertEqual(result["business_event_id"], "business-event")
        self.assertTrue(all(result["coverage"].values()))
        self.assertEqual(result["observer_http"]["queries_sharing_admission_request_id"], 0)
        self.assertEqual(result["observer_http"]["request_response_id_matches"], 1)
        self.assertEqual(result["original_classification"], "completed_late")
        self.assertNotIn("must not be exported", json.dumps(result))
        self.assertIn("durable_trace_context", result["unavailable_in_selected_sources"])
        self.assertEqual(inputs, before)

    def test_worker_request_id_collision_is_rejected(self):
        inputs = fixture()
        inputs[3].append(inputs[3][0].copy())
        with self.assertRaisesRegex(ValueError, "AMBIGUOUS_WORKER_RECORD"):
            discovery.correlate(*inputs)

    def test_worker_business_identity_must_match(self):
        inputs = fixture()
        inputs[3][0]["event_id"] = "different-event"
        with self.assertRaisesRegex(ValueError, "WORKER_EVENT_MISMATCH"):
            discovery.correlate(*inputs)

    def test_different_acceptance_journal_is_rejected(self):
        inputs = fixture()
        inputs[2][0]["inbox_id"] = "another-inbox"
        with self.assertRaisesRegex(ValueError, "ACCEPTANCE_JOURNAL_MISMATCH"):
            discovery.correlate(*inputs)

    def test_foreign_observations_are_rejected(self):
        inputs = fixture()
        inputs[4][-1]["notification_id"] = "another-notification"
        with self.assertRaisesRegex(ValueError, "OBSERVATION_NOTIFICATION_MISMATCH"):
            discovery.correlate(*inputs)

    def test_absent_telemetry_does_not_change_original_functional_result(self):
        inputs = fixture()
        inputs[3:] = [[], [], []]
        result = discovery.correlate(*inputs)
        self.assertEqual(result["original_classification"], "completed_late")
        self.assertFalse(result["coverage"]["core_done_linked_to_business_event"])
        self.assertIsNone(result["core_process_record"])
        self.assertTrue(result["coverage"]["acceptance_linked_to_journal"])

    def test_http_error_is_preserved_despite_later_success(self):
        inputs = fixture()
        inputs[-1].insert(0, {**inputs[-1][0], "http_status": 503})
        result = discovery.correlate(*inputs)
        self.assertEqual(result["observer_http"]["non_200"], 1)
        self.assertEqual(result["observer_http"]["get_count"], 2)

    def test_unknown_http_response_is_not_reported_as_received_non_200(self):
        inputs = fixture()
        inputs[-1][0].update(http_status=None, error="TIMEOUT")
        result = discovery.correlate(*inputs)
        self.assertEqual(result["observer_http"]["non_200"], 0)
        self.assertEqual(result["observer_http"]["transport_errors_or_unknown"], 1)

    def test_negative_or_nonfinite_intervals_are_rejected(self):
        for end in (19, float("nan"), float("inf")):
            with self.subTest(end=end):
                inputs = fixture()
                inputs[-1][0]["end_monotonic"] = end
                with self.assertRaisesRegex(ValueError, "INVALID_HTTP_INTERVAL"):
                    discovery.correlate(*inputs)

    def test_existing_output_is_not_overwritten_or_reanalyzed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "original.json"
            output.write_bytes(b"original")
            with patch("sys.argv", ["discovery", "--output", str(output)]):
                with patch.object(discovery, "discover") as read:
                    with self.assertRaisesRegex(ValueError, "OUTPUT_ALREADY_EXISTS"):
                        discovery.main()
                    read.assert_not_called()
            self.assertEqual(output.read_bytes(), b"original")

    def test_corrupt_archive_fails_before_reading_records(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(
                json.dumps({"archives": [{"path": "bad.zip", "sha256": "0" * 64}]})
            )
            (root / "bad.zip").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "ARCHIVE_HASH_MISMATCH"):
                discovery.discover(root)


if __name__ == "__main__":
    unittest.main()
