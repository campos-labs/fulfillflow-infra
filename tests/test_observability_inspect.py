"""Read-only inspection preserves inconclusive results and rejects mismatched identities."""

import json
import unittest
from types import SimpleNamespace

from scripts.observability_inspect import project_result


class InspectionTests(unittest.TestCase):
    def test_empty_success_does_not_claim_original_request_was_never_persisted(self):
        result = project_result(
            SimpleNamespace(status=200, body=b'{"items":[],"total":0}'), "event"
        )
        self.assertEqual(result["finding"], "no_record_returned")

    def test_unavailable_response_remains_inconclusive_without_exporting_body(self):
        result = project_result(SimpleNamespace(status=503, body=b"private"), "event")
        self.assertEqual(result, {"query_status": 503, "finding": "inconclusive"})

    def test_foreign_identity_and_inconsistent_count_rejected(self):
        for payload in (
            {"items": [{"external_event_id": "other"}], "total": 1},
            {"items": [], "total": 1},
        ):
            with self.assertRaises(RuntimeError):
                project_result(
                    SimpleNamespace(status=200, body=json.dumps(payload).encode()), "event"
                )

    def test_found_record_is_projected_without_payload_or_error_detail(self):
        payload = {
            "items": [
                {
                    "external_event_id": "event",
                    "status": "PROCESSED",
                    "payload": "private",
                    "error_detail": "private",
                }
            ],
            "total": 1,
        }
        result = project_result(
            SimpleNamespace(status=200, body=json.dumps(payload).encode()), "event"
        )
        self.assertEqual(result["finding"], "record_found")
        self.assertNotIn("private", json.dumps(result))
