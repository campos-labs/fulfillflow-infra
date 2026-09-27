"""Known failures must be classified independently and the intervention restored."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.http_trace_contract import LABEL
from scripts.http_trace_fault import run_sequence, verify_fault

ROOT = Path(__file__).resolve().parents[1]


def fault_records():
    result = {
        "complete": False,
        "status": 503,
        "error": "PUBLIC_QUERY_FAILED",
        "query_count": 1,
        "request_id_echoed": True,
        "trace_id": "trace",
    }
    rows = []
    for i, (service, kind) in enumerate(
        (("observer", "CLIENT"), ("core", "SERVER"), ("core", "CLIENT"))
    ):
        attrs = {"http.request.method": "GET", "http.route": "/api/v1/carrier-events"}
        if i == 2:
            attrs.update(
                {"http.route": "/internal/v1/tracking/carrier-events", "error.type": "transport"}
            )
        else:
            attrs["http.response.status_code"] = 503
        rows.append(
            {
                "trace_id": "trace",
                "span_id": str(i),
                "parent_span_id": str(i - 1) if i else None,
                "service": "httpdiag-" + service,
                "kind": "SPAN_KIND_" + kind,
                "attributes": attrs,
                "status": 2 if i else 0,
                "events": [],
                "start_time_unix_nano": 1,
                "end_time_unix_nano": 2,
            }
        )
    return {"accepted_batches": 2, "rejected_batches": 0, "records": rows}, result


class ControlledFailure(unittest.TestCase):
    def test_expected_failure_is_diagnostic_success_not_functional_success(self):
        snapshot, result = fault_records()
        self.assertTrue(verify_fault(snapshot, result, {"confirmed": True})["complete"])
        self.assertFalse(result["complete"])

    def test_missing_span_does_not_prove_injected_fault(self):
        snapshot, result = fault_records()
        with self.assertRaisesRegex(ValueError, "INDEPENDENTLY_CONFIRMED"):
            verify_fault(snapshot, result, {"confirmed": False})

    def test_reject_wrong_result_missing_export_and_remote_response(self):
        for mutation in ("status", "coverage", "rejected", "remote", "parent"):
            snapshot, result = fault_records()
            if mutation == "status":
                result["status"] = 200
            elif mutation == "coverage":
                snapshot["records"].pop()
            elif mutation == "rejected":
                snapshot["rejected_batches"] = 1
            elif mutation == "remote":
                snapshot["records"][2]["attributes"]["http.response.status_code"] = 503
            else:
                snapshot["records"][2]["parent_span_id"] = "unrelated"
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                verify_fault(snapshot, result, {"confirmed": True})

    def test_restores_after_capture_failure_even_with_measurement_guard_failure(self):
        service = {
            "metadata": {"uid": "uid", "labels": {LABEL: "true", "fulfillflow.io/http-run": "run"}},
            "spec": {
                "selector": {"app.kubernetes.io/name": "httpdiag-tracking"},
                "ports": [{"port": 8000}],
            },
        }
        initial = copy.deepcopy(service)
        calls = []

        def kube(args, **kwargs):
            calls.append(args)
            if args[:2] == ["get", "service"]:
                return json.dumps(service)
            if args[:2] == ["get", "pods"]:
                return '{"items": []}'
            if args[0] == "patch":
                ops = json.loads(args[-1])
                self.assertEqual(ops[0]["value"], service["metadata"]["uid"])
                self.assertEqual(ops[1]["value"], service["spec"]["selector"])
                service["spec"]["selector"] = ops[2]["value"]
                return ""
            raise AssertionError(args)

        healthy_dir = ROOT / "docs/evidence/observability/http-05"
        healthy = (
            json.loads((healthy_dir / "trace-records.json").read_bytes()),
            json.loads((healthy_dir / "functional.json").read_bytes()),
        )
        with tempfile.TemporaryDirectory() as directory:
            runner = SimpleNamespace(
                output=Path(directory), private=Path("private"), run_id="run", kube=kube
            )
            with (
                patch(
                    "scripts.http_trace_fault.await_endpoints", return_value={"ready_endpoints": 0}
                ),
                patch(
                    "scripts.http_trace_fault.env.kubectl",
                    side_effect=lambda private, args, **kw: kube(args),
                ),
                self.assertRaisesRegex(RuntimeError, "HOST_MEMORY_BELOW_GUARD"),
            ):
                capture = unittest.mock.Mock(
                    side_effect=[healthy, RuntimeError("HOST_MEMORY_BELOW_GUARD")]
                )
                run_sequence(runner, {}, capture)
            self.assertTrue(
                json.loads((Path(directory) / "restoration.json").read_bytes())[
                    "original_spec_restored"
                ]
            )
        self.assertEqual(service, initial)
        self.assertEqual(sum(args[0] == "patch" for args in calls), 2)
