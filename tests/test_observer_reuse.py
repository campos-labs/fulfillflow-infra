"""Reusing a response must not skip identity/result checks or cache pending state."""

import tempfile
import unittest
from contextlib import nullcontext
from pathlib import Path

from scripts.scale_calibration import _execute, observe
from scripts.verify_flow import Config, Evidence, Failure, Verifier
from tests.test_verify_flow import EVENT, INBOX, SHIPMENT, PublicApi


class ObserverReuseTests(unittest.TestCase):
    def workspace(self):
        # unittest closes Evidence before removing its directory, including on Windows.
        return nullcontext(self.enterContext(tempfile.TemporaryDirectory()))

    def prepared(self, directory, api):
        evidence = Evidence(Path(directory) / "evidence")
        self.addCleanup(evidence.close)
        verifier = Verifier(
            Config("http://127.0.0.1:8000", Path(directory), secret="synthetic"), evidence, api
        )
        order, shipment, code = verifier.prepare()
        inbox, _ = verifier.admit(*verifier.webhook(code))
        item = {
            "event_id": verifier.event_id,
            "order_id": order,
            "shipment_id": shipment,
            "inbox_id": inbox,
        }
        api.requests.clear()
        return verifier, item

    def test_same_completion_checks_with_six_instead_of_eight_reads(self):
        for reuse, count in ((False, 8), (True, 6)):
            with self.subTest(reuse=reuse), self.workspace() as directory:
                api = PublicApi()
                verifier, item = self.prepared(directory, api)
                result = observe(verifier, item, reuse_terminal_reads=reuse)
                self.assertTrue(result["effects_unique"])
                self.assertTrue(verifier.tracking_completed)
                self.assertTrue(verifier.order_completed)
                self.assertTrue(verifier.notifications_simulated)
                self.assertEqual(len(api.requests), count)
                self.assertTrue(all(r[0] == "GET" for r in api.requests))

    def test_reused_tracking_response_still_checks_result_identity(self):
        with self.workspace() as directory:
            api = PublicApi()
            api.bad_tracking_identity = True
            verifier, item = self.prepared(directory, api)
            result = observe(verifier, item, reuse_terminal_reads=True)
            self.assertEqual(result["observation_error"], "SCHEMA_UNEXPECTED")
            self.assertFalse(verifier.tracking_completed)
            self.assertEqual(len(api.requests), 1)

    def test_reused_notification_response_still_checks_required_and_identity(self):
        for field, value in (("required", False), ("tracking_event_id", INBOX), ("status", "SENT")):
            with self.subTest(field=field), self.workspace() as directory:
                api = PublicApi()
                verifier, _ = self.prepared(directory, api)
                record = verifier.get("/api/v1/notification-status/" + EVENT)
                record[field] = value
                api.requests.clear()
                with self.assertRaises(Failure):
                    verifier.notifications(EVENT, initial_record=record)
                self.assertFalse(verifier.notifications_simulated)
                self.assertEqual(api.requests, [])

    def test_pending_response_is_not_cached_across_observations(self):
        with self.workspace() as directory:
            api = PublicApi(tracking=["QUEUED", "PROCESSED"])
            verifier, item = self.prepared(directory, api)
            self.assertTrue(observe(verifier, item, reuse_terminal_reads=True)["pending_confirmed"])
            self.assertTrue(observe(verifier, item, reuse_terminal_reads=True)["effects_unique"])
            self.assertEqual(len(api.requests), 7)

    def test_initial_pending_record_is_consumed_once_and_then_fetches(self):
        with self.workspace() as directory:
            api = PublicApi(tracking=["QUEUED", "PROCESSED"])
            verifier, _ = self.prepared(directory, api)
            path = "/api/v1/carrier-events/" + INBOX
            record = verifier.get(path)
            verifier.sleep = lambda seconds: None
            self.assertEqual(verifier.tracking(INBOX, path, SHIPMENT, initial_record=record), EVENT)
            self.assertEqual(len(api.requests), 2)

    def test_reuse_cannot_silently_change_standard_calibration(self):
        with self.assertRaisesRegex(RuntimeError, "REUSE_REQUIRES_DIAGNOSTIC"):
            _execute(None, None, reuse_terminal_reads=True)
