"""Offline contract tests: every HTTP response and observation clock is injected."""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import importlib.util
import io
import json
import queue
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify_flow.py"
SPEC = importlib.util.spec_from_file_location("verify_flow_under_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
flow = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = flow
SPEC.loader.exec_module(flow)

ORDER = "10000000-0000-4000-8000-000000000001"
SHIPMENT = "10000000-0000-4000-8000-000000000002"
INBOX = "10000000-0000-4000-8000-000000000003"
EVENT = "10000000-0000-4000-8000-000000000004"
NOTIFICATION = "10000000-0000-4000-8000-000000000005"
REQUEST = "10000000-0000-4000-8000-000000000006"
STAMP = "2026-09-19T12:00:00+00:00"
SECRET = "test-only-sensitive-token-never-printed"


def response(payload, status=200, **headers):
    return flow.Response(
        status, {"content-type": "application/json", **headers}, flow.json_bytes(payload)
    )


class Clock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def sleep(self, seconds):
        self.elapsed += seconds

    def now(self):
        return datetime.fromisoformat(STAMP)


class PublicApi:
    """Minimal frozen projections; no sockets, persistence, workers or background work."""

    def __init__(self, *, carrier="carrier-alpha", tracking=None, notifications=None):
        self.carrier = carrier
        self.tracking_states = list(tracking or ["PROCESSED"])
        self.notification_states = list(notifications or ["DONE"])
        self.requests = []
        self.webhooks = []
        self.location = f"/api/v1/carrier-events/{INBOX}"
        self.first_webhook_status = 202
        self.query_status = 200
        self.extra_notification = False
        self.bad_tracking_identity = False
        self.pending_event_id = None
        self.tracking_code = None
        self.event_id = None

    def __call__(self, method, url, headers, body, timeout):
        self.requests.append((method, url, dict(headers), body, timeout))
        path = urlsplit(url).path
        payload = json.loads(body) if body else None
        if path == "/api/v1/orders" and method == "POST":
            return response({"id": ORDER, "status": "CREATED"}, 201)
        if path == f"/api/v1/orders/{ORDER}/confirm":
            return response({"id": ORDER, "status": "CONFIRMED"})
        if path == "/api/v1/shipments" and method == "POST":
            self.tracking_code = payload["tracking_code"]
            return response(
                {
                    "id": SHIPMENT,
                    "order_id": ORDER,
                    "status": "PENDING",
                    "carrier_code": self.carrier,
                    "tracking_code": self.tracking_code,
                },
                201,
            )
        if path == f"/api/v1/carriers/{self.carrier}/events":
            self.webhooks.append((body, dict(headers)))
            self.event_id = headers["X-FulfillFlow-Event-Id"]
            if len(self.webhooks) == 1:
                return response(
                    {
                        "inbox_event_id": INBOX,
                        "external_event_id": self.event_id,
                        "status": "RECEIVED",
                        "received_at": STAMP,
                        "request_id": REQUEST,
                    },
                    self.first_webhook_status,
                    location=self.location,
                )
            return response(
                {
                    "external_event_id": self.event_id,
                    "inbox_event_id": INBOX,
                    "tracking_event_id": EVENT,
                    "result": "DUPLICATE",
                    "original_result": "APPLIED",
                    "shipment_id": SHIPMENT,
                    "previous_status": "PENDING",
                    "current_status": "DELIVERED",
                }
            )
        if path == f"/api/v1/carrier-events/{INBOX}":
            if self.query_status != 200:
                return response(
                    {"detail": SECRET, "url": "https://credential:secret@unsafe.test"},
                    self.query_status,
                )
            state = self.tracking_states[0]
            if len(self.tracking_states) > 1:
                self.tracking_states.pop(0)
            status = state if state in ("PROCESSED", "REJECTED") else "RECEIVED"
            progress = "COMPLETED" if status in ("PROCESSED", "REJECTED") else state
            return response(
                {
                    "id": INBOX,
                    "external_event_id": self.event_id,
                    "carrier_code": self.carrier,
                    "status": status,
                    "progress": progress,
                    "tracking_event_id": EVENT if state == "PROCESSED" else self.pending_event_id,
                    "completed_at": STAMP if state == "PROCESSED" else None,
                    "result": {
                        "kind": "applied",
                        "result": "APPLIED",
                        "decided_at": STAMP,
                        "event_id": REQUEST if self.bad_tracking_identity else EVENT,
                        "shipment_id": SHIPMENT,
                        "previous_status": "PENDING",
                        "current_status": "DELIVERED",
                    }
                    if state == "PROCESSED"
                    else None,
                }
            )
        if path == f"/api/v1/shipments/{SHIPMENT}":
            return response(
                {
                    "id": SHIPMENT,
                    "order_id": ORDER,
                    "status": "DELIVERED",
                    "status_external_event_id": self.event_id,
                }
            )
        if path == f"/api/v1/orders/{ORDER}":
            return response({"id": ORDER, "status": "FULFILLED"})
        if path == f"/api/v1/notification-status/{EVENT}":
            state = self.notification_states[0]
            if len(self.notification_states) > 1:
                self.notification_states.pop(0)
            return response(
                {
                    "tracking_event_id": EVENT,
                    "required": True,
                    "publication": "SENT",
                    "processing": state,
                    "status": "SIMULATED" if state == "DONE" else None,
                    "notification_id": NOTIFICATION if state == "DONE" else None,
                    "simulated_at": STAMP if state == "DONE" else None,
                }
            )
        if path == f"/api/v1/shipments/{SHIPMENT}/tracking":
            return response(
                {
                    "items": [
                        {
                            "id": EVENT,
                            "inbox_event_id": INBOX,
                            "shipment_id": SHIPMENT,
                            "application_result": "APPLIED",
                            "resulting_shipment_status": "DELIVERED",
                        }
                    ],
                    "page": 1,
                    "page_size": 2,
                    "total": 1,
                }
            )
        if path == "/api/v1/notifications":
            item = {
                "id": NOTIFICATION,
                "tracking_event_id": EVENT,
                "shipment_id": SHIPMENT,
                "status": "SIMULATED",
            }
            duplicated = self.extra_notification and len(self.webhooks) == 2
            return response(
                {
                    "items": [item, item] if duplicated else [item],
                    "page": 1,
                    "page_size": 2,
                    "total": 2 if duplicated else 1,
                }
            )
        raise AssertionError(f"Unexpected test request: {method} {path}")


class FlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.parent = Path(self.temp.name)

    def verifier(self, api=None, **config_values):
        api = api or PublicApi()
        self.output = self.parent / "new evidence"
        evidence = flow.Evidence(self.output)
        self.addCleanup(evidence.close)
        config = flow.Config("http://127.0.0.1:8000", self.output, secret=SECRET, **config_values)
        config.validate()
        clock = Clock()
        verifier = flow.Verifier(
            config, evidence, api, monotonic=clock.monotonic, sleep=clock.sleep, now=clock.now
        )
        return verifier, api, clock

    def records(self):
        return [
            json.loads(line)
            for line in (self.output / "observations.jsonl").read_text().splitlines()
        ]

    def test_both_carriers_complete_with_one_intentional_same_byte_duplicate(self):
        for carrier in ("carrier-alpha", "carrier-beta"):
            with self.subTest(carrier=carrier), tempfile.TemporaryDirectory() as directory:
                evidence = flow.Evidence(Path(directory) / "evidence")
                self.addCleanup(evidence.close)
                clock, api = (
                    Clock(),
                    PublicApi(
                        carrier=carrier,
                        tracking=["QUEUED", "AWAITING_RESULT", "PROCESSED"],
                        notifications=["NOT_RECEIVED", "PENDING", "RETRY_WAIT", "DONE"],
                    ),
                )
                verifier = flow.Verifier(
                    flow.Config(
                        "http://localhost:8000", Path(directory), carrier=carrier, secret=SECRET
                    ),
                    evidence,
                    api,
                    monotonic=clock.monotonic,
                    sleep=clock.sleep,
                    now=clock.now,
                )
                verifier.run()
                self.assertTrue(
                    all(
                        verifier.summary(True)[key]
                        for key in (
                            "acceptance_verified",
                            "tracking_completed",
                            "order_completed",
                            "notifications_simulated",
                            "duplicate_verified",
                        )
                    )
                )
                self.assertEqual(len(api.webhooks), 2)
                first, duplicate = api.webhooks
                self.assertIs(first[0], duplicate[0])
                self.assertEqual(first[0], duplicate[0])
                event_id = first[1]["X-FulfillFlow-Event-Id"]
                signed_at = first[1]["X-FulfillFlow-Timestamp"]
                expected = (
                    "sha256="
                    + hmac.new(
                        SECRET.encode(),
                        signed_at.encode() + b"." + event_id.encode() + b"." + first[0],
                        hashlib.sha256,
                    ).hexdigest()
                )
                self.assertEqual(first[1]["X-FulfillFlow-Signature"], expected)
                decoded = json.loads(first[0])
                self.assertEqual(
                    decoded["status"] if carrier == "carrier-alpha" else decoded["event"]["type"],
                    "DELIVERED" if carrier == "carrier-alpha" else "completed",
                )
                reads = [request for request in api.requests if request[0] == "GET"]
                self.assertTrue(
                    all("X-FulfillFlow-Signature" not in request[2] for request in reads)
                )
                text = (Path(directory) / "evidence" / "observations.jsonl").read_text()
                self.assertNotIn(SECRET, text)
                self.assertNotIn("sha256=", text)
                self.assertNotIn("functional-smoke@example.test", text)
                evidence.close()

    def test_hmac_preserves_noncanonical_utf8_bytes(self):
        raw = b'{ "city" : "S\xc3\xa3o Paulo", "x": 1 }\n'
        expected = (
            "sha256=" + hmac.new(b"secret", b"123.event-1." + raw, hashlib.sha256).hexdigest()
        )
        self.assertEqual(flow.signature("secret", "123", "event-1", raw), expected)
        self.assertNotEqual(
            flow.signature("secret", "123", "event-1", flow.json_bytes(json.loads(raw))), expected
        )

    def test_deadline_keeps_acceptance_and_does_not_resend(self):
        verifier, api, clock = self.verifier(
            PublicApi(tracking=["AWAITING_RESULT"]), deadline_seconds=2
        )
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(
            (caught.exception.code, caught.exception.exit_code), ("OBSERVATION_DEADLINE", 5)
        )
        self.assertEqual(clock.elapsed, 2)
        self.assertTrue(verifier.accepted)
        self.assertFalse(verifier.tracking_completed)
        self.assertEqual(len(api.webhooks), 1)
        self.assertTrue(all(0 < request[4] <= 2 for request in api.requests))

    def test_pending_projection_with_event_id_waits_for_terminal_result(self):
        # Recorded series-02 attempt 18: READ COMMITTED queries can straddle finalization.
        api = PublicApi(tracking=["AWAITING_RESULT", "PROCESSED"])
        api.pending_event_id = EVENT
        verifier, api, clock = self.verifier(api)
        verifier.run()
        self.assertGreater(clock.elapsed, 0)
        self.assertTrue(verifier.tracking_completed and verifier.duplicate_verified)
        self.assertEqual(len(api.webhooks), 2)
        kinds = [item["phase"] for item in self.records()]
        self.assertLess(kinds.index("tracking_pending"), kinds.index("tracking_completed"))

    def test_pending_event_id_alone_never_proves_completion(self):
        api = PublicApi(tracking=["AWAITING_RESULT"])
        api.pending_event_id = EVENT
        verifier, api, _ = self.verifier(api, deadline_seconds=2)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "OBSERVATION_DEADLINE")
        self.assertTrue(verifier.accepted)
        self.assertFalse(verifier.tracking_completed or verifier.duplicate_verified)
        self.assertEqual(len(api.webhooks), 1)

    def test_malformed_pending_event_id_stops_without_resend(self):
        api = PublicApi(tracking=["AWAITING_RESULT", "PROCESSED"])
        api.pending_event_id = "not-a-uuid"
        verifier, api, _ = self.verifier(api)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "SCHEMA_UNEXPECTED")
        self.assertFalse(verifier.tracking_completed)
        self.assertEqual(len(api.webhooks), 1)

    def test_terminal_event_id_must_match_observed_pending_identity(self):
        api = PublicApi(tracking=["AWAITING_RESULT", "PROCESSED"])
        api.pending_event_id = REQUEST
        verifier, api, clock = self.verifier(api)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "SCHEMA_UNEXPECTED")
        self.assertGreater(clock.elapsed, 0)
        self.assertFalse(verifier.tracking_completed)
        self.assertEqual(len(api.webhooks), 1)

    def test_query_503_preserves_acceptance_and_stops_on_first_failure(self):
        api = PublicApi()
        api.query_status = 503
        verifier, api, _ = self.verifier(api)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "HTTP_STATUS_UNEXPECTED")
        self.assertTrue(verifier.accepted)
        self.assertEqual(len(api.webhooks), 1)
        self.assertEqual(sum("/carrier-events/" in request[1] for request in api.requests), 1)
        self.assertNotIn(SECRET, (self.output / "observations.jsonl").read_text())

    def test_off_origin_and_malformed_location_are_rejected_before_query(self):
        for location in (
            "https://public.example/secret",
            "//user:password@127.0.0.1:8000/api/v1/carrier-events/" + INBOX,
            "http://[",
            f"/api/v1/carrier-events/{INBOX}?secret=yes",
            "/api/v1/carrier-events/wrong",
        ):
            with self.subTest(location=location), tempfile.TemporaryDirectory() as directory:
                evidence = flow.Evidence(Path(directory) / "new")
                api = PublicApi()
                api.location = location
                verifier = flow.Verifier(
                    flow.Config("http://127.0.0.1:8000", Path(directory), secret=SECRET),
                    evidence,
                    api,
                )
                try:
                    with self.assertRaises(flow.Failure) as caught:
                        verifier.run()
                    self.assertEqual(caught.exception.code, "INVALID_LOCATION")
                    self.assertTrue(verifier.accepted)
                    self.assertEqual(len(api.requests), 4)
                finally:
                    evidence.close()

    def test_fresh_event_200_is_never_accepted_as_duplicate(self):
        api = PublicApi()
        api.first_webhook_status = 200
        verifier, api, _ = self.verifier(api)
        with self.assertRaises(flow.Failure):
            verifier.run()
        self.assertFalse(verifier.accepted)
        self.assertEqual(len(api.webhooks), 1)

    def test_no_duplicate_is_sent_while_notifications_pending(self):
        verifier, api, _ = self.verifier(PublicApi(notifications=["PENDING"]), deadline_seconds=2)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "OBSERVATION_DEADLINE")
        self.assertTrue(verifier.tracking_completed and verifier.order_completed)
        self.assertFalse(verifier.notifications_simulated)
        self.assertEqual(len(api.webhooks), 1)

    def test_tracking_blocked_and_rejected_are_terminal_failures(self):
        for state in ("BLOCKED_LOCAL", "REJECTED"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                evidence = flow.Evidence(Path(directory) / "new")
                api = PublicApi(tracking=[state])
                verifier = flow.Verifier(
                    flow.Config("http://localhost", Path(directory), secret=SECRET), evidence, api
                )
                try:
                    with self.assertRaises(flow.Failure) as caught:
                        verifier.run()
                    self.assertEqual(caught.exception.exit_code, 6)
                    self.assertEqual(len(api.webhooks), 1)
                finally:
                    evidence.close()

    def test_notifications_blocked_are_not_rearmed(self):
        verifier, api, _ = self.verifier(PublicApi(notifications=["BLOCKED"]))
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "NOTIFICATIONS_BLOCKED")
        self.assertEqual(len(api.webhooks), 1)

    def test_wrong_tracking_identity_fails(self):
        api = PublicApi()
        api.bad_tracking_identity = True
        verifier, api, _ = self.verifier(api)
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "SCHEMA_UNEXPECTED")
        self.assertFalse(verifier.tracking_completed)
        self.assertEqual(len(api.webhooks), 1)

    def test_duplicate_extra_effect_fails_without_another_resend(self):
        api = PublicApi()
        api.extra_notification = True
        verifier, api, _ = self.verifier(api)
        with self.assertRaises(flow.Failure):
            verifier.run()
        self.assertFalse(verifier.duplicate_verified)
        self.assertEqual(len(api.webhooks), 2)

    def test_invalid_json_schema_size_and_media_type_fail_safely(self):
        for raw, media in (
            (b"[]", "application/json"),
            (b'{"x":1,"x":2}', "application/json"),
            (b'{"x":NaN}', "application/json"),
            (b"\xff", "application/json"),
            (b"x" * (flow.MAX_RESPONSE_BYTES + 1), "application/json"),
            (b"{}", "text/html"),
            (b"[" * 2000, "application/json"),
        ):
            with (
                self.subTest(media=media, length=len(raw)),
                tempfile.TemporaryDirectory() as directory,
            ):
                evidence = flow.Evidence(Path(directory) / "new")
                verifier = flow.Verifier(
                    flow.Config("http://localhost", Path(directory), secret=SECRET),
                    evidence,
                    lambda *args: flow.Response(200, {"content-type": media}, raw),
                )
                try:
                    with self.assertRaises(flow.Failure):
                        verifier.get("/api/v1/orders")
                finally:
                    evidence.close()

    def test_invalid_progress_value_is_schema_failure_not_type_error(self):
        verifier, _, _ = self.verifier(PublicApi(tracking=[["QUEUED"]]))
        with self.assertRaises(flow.Failure) as caught:
            verifier.run()
        self.assertEqual(caught.exception.code, "SCHEMA_UNEXPECTED")

    def test_run_identity_is_unique(self):
        verifier, _, _ = self.verifier()
        other = flow.Verifier(verifier.config, verifier.evidence, PublicApi())
        self.assertNotEqual(verifier.run_id, other.run_id)
        self.assertNotEqual(verifier.event_id, other.event_id)

    def test_output_directory_exists_fails_without_overwrite_or_request(self):
        existing = self.parent / "existing"
        existing.mkdir()
        sentinel = existing / "observations.jsonl"
        sentinel.write_text("preserve me", encoding="utf-8")
        transport = Mock()
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(existing)],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=transport,
            )
        self.assertEqual(result, 2)
        self.assertEqual(sentinel.read_text(), "preserve me")
        transport.assert_not_called()
        self.assertIn("OUTPUT_UNAVAILABLE_OR_EXISTS", error.getvalue())

    def test_main_redacts_response_and_transport_exception_and_keeps_evidence(self):
        api = PublicApi()
        api.query_status = 503
        out, err = io.StringIO(), io.StringIO()
        output = self.parent / "failed"
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(output)],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=api,
            )
        self.assertEqual(result, 3)
        summary = json.loads(err.getvalue())
        self.assertTrue(summary["acceptance_verified"])
        evidence = (output / "observations.jsonl").read_text()
        for secret in (SECRET, "credential:secret", "unsafe.test", "sha256="):
            self.assertNotIn(secret, out.getvalue() + err.getvalue() + evidence)
        self.assertEqual(json.loads(evidence.splitlines()[-1])["phase"], "failed")

    def test_main_success_outputs_separate_completion_booleans(self):
        out, err = io.StringIO(), io.StringIO()
        output = self.parent / "successful"
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(output)],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=PublicApi(),
            )
        self.assertEqual(result, 0)
        self.assertEqual(err.getvalue(), "")
        self.assertTrue(json.loads(out.getvalue())["duplicate_verified"])
        started = json.loads((output / "observations.jsonl").read_text().splitlines()[0])
        self.assertEqual(started["expected_application_sha"], flow.EXPECTED_APPLICATION_SHA)
        self.assertIs(started["runtime_identity_verified"], False)
        self.assertNotIn("app_sha", started)

    def test_close_failure_preserves_original_http_failure(self):
        evidence = Mock(spec=flow.Evidence)
        evidence.close.side_effect = OSError(SECRET)
        api = PublicApi()
        api.query_status = 503
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(flow, "Evidence", return_value=evidence),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(self.parent / "failed")],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=api,
            )
        self.assertEqual(result, 3)
        summary = json.loads(err.getvalue())
        self.assertEqual(summary["error"], "HTTP_STATUS_UNEXPECTED")
        self.assertTrue(summary["acceptance_verified"])
        self.assertTrue(summary["evidence_close_failed"])
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn(SECRET, err.getvalue())
        evidence.close.assert_called_once()

    def test_close_failure_preserves_interruption(self):
        evidence = Mock(spec=flow.Evidence)
        evidence.close.side_effect = OSError(SECRET)
        out, err = io.StringIO(), io.StringIO()
        transport = Mock()
        with (
            patch.object(flow, "Evidence", return_value=evidence),
            patch.object(flow.Verifier, "run", side_effect=KeyboardInterrupt(SECRET)),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(self.parent / "failed")],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=transport,
            )
        self.assertEqual(result, 130)
        summary = json.loads(err.getvalue())
        self.assertEqual(summary["error"], "INTERRUPTED_OUTCOME_UNKNOWN")
        self.assertTrue(summary["evidence_close_failed"])
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn(SECRET, err.getvalue())
        transport.assert_not_called()

    def test_write_and_close_failures_are_both_sanitized(self):
        evidence = Mock(spec=flow.Evidence)
        evidence.emit.side_effect = OSError(SECRET)
        evidence.close.side_effect = OSError(SECRET)
        out, err = io.StringIO(), io.StringIO()
        transport = Mock()
        with (
            patch.object(flow, "Evidence", return_value=evidence),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(self.parent / "failed")],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=transport,
            )
        self.assertEqual(result, 2)
        summary = json.loads(err.getvalue())
        self.assertEqual(summary["error"], "EVIDENCE_IO_FAILED")
        self.assertTrue(summary["evidence_write_failed"])
        self.assertTrue(summary["evidence_close_failed"])
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn(SECRET, err.getvalue())
        evidence.close.assert_called_once()
        transport.assert_not_called()

    def test_close_failure_after_success_emits_only_a_failure_summary(self):
        evidence = Mock(spec=flow.Evidence)
        evidence.close.side_effect = OSError(SECRET)
        out, err = io.StringIO(), io.StringIO()
        with (
            patch.object(flow, "Evidence", return_value=evidence),
            contextlib.redirect_stdout(out),
            contextlib.redirect_stderr(err),
        ):
            result = flow.main(
                ["--base-url", "http://localhost", "--output-dir", str(self.parent / "failed")],
                environ={"CARRIER_ALPHA_WEBHOOK_SECRET": SECRET},
                transport=PublicApi(),
            )
        self.assertEqual(result, 2)
        summary = json.loads(err.getvalue())
        self.assertEqual(summary["error"], "EVIDENCE_IO_FAILED")
        self.assertFalse(summary["success"])
        self.assertTrue(summary["duplicate_verified"])
        self.assertTrue(summary["evidence_close_failed"])
        self.assertEqual(out.getvalue(), "")
        self.assertNotIn(SECRET, err.getvalue())

    def test_secret_is_environment_only_and_invalid_arguments_do_not_echo_it(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit) as caught:
            flow.main(["--secret", SECRET])
        self.assertEqual(caught.exception.code, 2)
        self.assertNotIn(SECRET, error.getvalue())
        transport = Mock()
        error = io.StringIO()
        with contextlib.redirect_stderr(error):
            result = flow.main(
                [
                    "--base-url",
                    "http://localhost",
                    "--output-dir",
                    str(self.parent / "missing-secret"),
                ],
                environ={},
                transport=transport,
            )
        self.assertEqual(result, 2)
        transport.assert_not_called()


class TransportAndConfigTests(unittest.TestCase):
    def test_origin_allowlist_requires_loopback_or_private_ip_https(self):
        for value in (
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://[::1]:8000/",
            "https://10.1.2.3",
            "https://172.16.0.1",
            "https://192.168.1.1",
            "https://[fd00::1]",
        ):
            self.assertEqual(flow.base_url(value), value.rstrip("/"))
        for value in (
            "https://example.com",
            "http://10.1.2.3",
            "https://8.8.8.8",
            "http://0.0.0.0",
            "https://100.64.0.1",
            "https://169.254.169.254",
            "https://192.0.2.1",
            "http://user:secret@localhost",
            "http://localhost/path",
            "http://localhost?secret=yes",
            "http://localhost#fragment",
            "http://[",
            "http://localhost:0",
            "http://localhost:65536",
            " http://localhost",
            "http://localhost\\@evil.test",
        ):
            with self.subTest(value=value), self.assertRaises(flow.Failure):
                flow.base_url(value)

    def test_nonfinite_and_excessive_time_limits_fail(self):
        for values in (
            {"deadline_seconds": float("nan")},
            {"deadline_seconds": 301},
            {"request_timeout_seconds": float("inf")},
            {"poll_seconds": 0},
        ):
            with self.subTest(values=values), self.assertRaises(flow.Failure):
                flow.Config("http://localhost", Path("unused"), secret=SECRET, **values).validate()

    def test_transport_ignores_proxy_environment_and_does_not_follow_redirect(self):
        reply = Mock(status=302)
        reply.read.return_value = b"{}"
        reply.getheaders.return_value = [
            ("Location", "https://unsafe.test"),
            ("Content-Type", "application/json"),
        ]
        connection = Mock()
        connection.getresponse.return_value = reply
        with (
            patch.object(
                flow.http.client, "HTTPConnection", return_value=connection
            ) as constructor,
            patch.dict(flow.os.environ, {"HTTP_PROXY": "http://unsafe.test"}),
        ):
            result = flow.HttpTransport()(
                "POST", "http://localhost:8000/api/v1/test", {"X-Secret": SECRET}, b"{}", 1
            )
        self.assertEqual(result.status, 302)
        constructor.assert_called_once_with("127.0.0.1", 8000, timeout=1)
        connection.request.assert_called_once()
        connection.close.assert_called_once()

    def test_transport_caps_body_and_rejects_duplicate_location(self):
        for content, headers, expected in (
            (b"x" * (flow.MAX_RESPONSE_BYTES + 1), [], "RESPONSE_TOO_LARGE"),
            (b"{}", [("Location", "/one"), ("location", "/two")], "SCHEMA_UNEXPECTED"),
        ):
            reply = Mock(status=200)
            reply.read.return_value, reply.getheaders.return_value = content, headers
            connection = Mock()
            connection.getresponse.return_value = reply
            with (
                patch.object(flow.http.client, "HTTPConnection", return_value=connection),
                self.assertRaises(flow.Failure) as caught,
            ):
                flow.HttpTransport()("GET", "http://127.0.0.1/test", {}, None, 1)
            self.assertEqual(caught.exception.code, expected)
            reply.read.assert_called_once_with(flow.MAX_RESPONSE_BYTES + 1)

    def test_transport_error_message_is_not_exposed(self):
        with (
            patch.object(flow.http.client, "HTTPConnection", side_effect=OSError(SECRET)),
            self.assertRaises(flow.Failure) as caught,
        ):
            flow.HttpTransport()("GET", "http://127.0.0.1/test", {}, None, 1)
        self.assertEqual(str(caught.exception), "HTTP_TRANSPORT_FAILED")
        self.assertIsNone(caught.exception.__cause__)

    def test_total_http_timeout_is_bounded_without_real_sleep_or_network(self):
        fake_queue = Mock()
        fake_queue.get.side_effect = queue.Empty
        with (
            patch.object(flow.queue, "Queue", return_value=fake_queue),
            patch.object(flow.threading, "Thread") as thread,
            self.assertRaises(flow.Failure) as caught,
        ):
            flow.HttpTransport()("POST", "http://127.0.0.1/test", {}, b"{}", 0.5)
        self.assertEqual(caught.exception.code, "HTTP_TIMEOUT_OUTCOME_UNKNOWN")
        fake_queue.get.assert_called_once_with(timeout=0.5)
        self.assertTrue(thread.call_args.kwargs["daemon"])
        thread.return_value.start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
