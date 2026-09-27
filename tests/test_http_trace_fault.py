"""Known failures must be classified independently and the intervention restored."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.http_trace_contract import LABEL
from scripts.http_trace_fault import await_endpoints, await_no_pods, run_sequence, verify_fault

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
    def test_empty_endpoint_slice_can_be_null_empty_or_absent(self):
        for item in ({"endpoints": None}, {"endpoints": []}, {}):
            with self.subTest(item=item):
                runner = SimpleNamespace(kube=lambda args: json.dumps({"items": [item]}))
                self.assertEqual(await_endpoints(runner, False)["ready_endpoints"], 0)

    def test_null_slice_does_not_hide_ready_endpoint_or_approve_recovery(self):
        runner = SimpleNamespace(
            kube=unittest.mock.Mock(
                side_effect=[
                    json.dumps({"items": [{"endpoints": None}]}),
                    json.dumps(
                        {
                            "items": [
                                {"endpoints": None},
                                {
                                    "endpoints": [
                                        {"conditions": {"ready": True}},
                                        {"conditions": {"ready": False}},
                                    ]
                                },
                            ]
                        }
                    ),
                ]
            )
        )
        with patch("scripts.http_trace_fault.time.sleep"):
            self.assertEqual(await_endpoints(runner, True)["ready_endpoints"], 1)
        self.assertEqual(runner.kube.call_count, 2)

    def test_terminating_pod_is_not_considered_removed(self):
        pod = {
            "metadata": {
                "uid": "old",
                "deletionTimestamp": "now",
                "labels": {"fulfillflow.io/http-run": "run"},
            }
        }
        runner = SimpleNamespace(
            run_id="run",
            kube=unittest.mock.Mock(
                side_effect=[json.dumps({"items": [pod]}), json.dumps({"items": []})]
            ),
        )
        with patch("scripts.http_trace_fault.time.sleep"):
            self.assertEqual(await_no_pods(runner)["remaining_pods"], 0)
        self.assertEqual(runner.kube.call_count, 2)

    def test_foreign_pod_aborts_injection(self):
        runner = SimpleNamespace(
            run_id="run",
            kube=lambda args: json.dumps(
                {"items": [{"metadata": {"uid": "foreign", "labels": {}}}]}
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "FAULT_POD_IDENTITY"):
            await_no_pods(runner)

    def test_expected_failure_is_diagnostic_success_not_functional_success(self):
        snapshot, result = fault_records()
        self.assertTrue(
            verify_fault(
                snapshot,
                result,
                {
                    "confirmed": True,
                    "mechanism": "diagnostic_api_scale_to_zero",
                    "pod_state": {"remaining_pods": 0},
                },
            )["complete"]
        )
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
                verify_fault(
                    snapshot,
                    result,
                    {
                        "confirmed": True,
                        "mechanism": "diagnostic_api_scale_to_zero",
                        "pod_state": {"remaining_pods": 0},
                    },
                )

    def test_endpoints_only_no_longer_confirm_interruption(self):
        snapshot, result = fault_records()
        with self.assertRaisesRegex(ValueError, "INDEPENDENTLY_CONFIRMED"):
            verify_fault(
                snapshot, result, {"confirmed": True, "endpoint_state": {"ready_endpoints": 0}}
            )

    def test_complete_sequence_restores_and_checks_new_ready_pod(self):
        deployment = {
            "metadata": {"uid": "dep", "labels": {LABEL: "true", "fulfillflow.io/http-run": "run"}},
            "spec": {
                "replicas": 1,
                "selector": {"matchLabels": {"app.kubernetes.io/name": "httpdiag-tracking"}},
            },
        }
        service = {
            "metadata": {"uid": "svc"},
            "spec": {"selector": {"app.kubernetes.io/name": "httpdiag-tracking"}},
        }
        recreated = False

        def kube(args, **kwargs):
            nonlocal recreated
            if args[:2] == ["get", "deployment"]:
                return json.dumps(deployment)
            if args[:2] == ["get", "service"]:
                return json.dumps(service)
            if args[:2] == ["get", "pods"]:
                pods = (
                    []
                    if deployment["spec"]["replicas"] == 0
                    else [
                        {
                            "metadata": {
                                "uid": "new" if recreated else "old",
                                "labels": {"fulfillflow.io/http-run": "run"},
                            },
                            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
                        }
                    ]
                )
                return json.dumps({"items": pods})
            if args[:2] == ["get", "endpointslice"]:
                return json.dumps(
                    {
                        "items": [
                            {
                                "endpoints": [{"conditions": {"ready": True}}]
                                if deployment["spec"]["replicas"]
                                else None
                            }
                        ]
                    }
                )
            if args[0] == "patch":
                ops = json.loads(args[-1])
                self.assertEqual(ops[0]["value"], "dep")
                self.assertEqual(ops[1]["value"], deployment["spec"]["replicas"])
                deployment["spec"]["replicas"] = ops[2]["value"]
                recreated = recreated or ops[2]["value"] == 1
                return ""
            if args[0] == "rollout":
                return ""
            raise AssertionError(args)

        directory = ROOT / "docs/evidence/observability/http-05"
        before = (
            json.loads((directory / "trace-records.json").read_bytes()),
            json.loads((directory / "functional.json").read_bytes()),
        )
        after = copy.deepcopy(before)
        after[1]["trace_id"] = "after"
        for row in after[0]["records"]:
            row["trace_id"] = "after"
        with tempfile.TemporaryDirectory() as output:
            runner = SimpleNamespace(
                output=Path(output), private=Path("private"), run_id="run", kube=kube
            )
            capture = unittest.mock.Mock(side_effect=[before, fault_records(), after])
            with patch(
                "scripts.http_trace_fault.env.kubectl",
                side_effect=lambda private, args, **kw: kube(args),
            ):
                run_sequence(runner, {}, capture)
            self.assertTrue(json.loads((Path(output) / "review.json").read_bytes())["complete"])
            self.assertEqual(
                json.loads((Path(output) / "restored-pod.json").read_bytes())["uid"], "new"
            )
            self.assertEqual(capture.call_count, 3)
            self.assertEqual(deployment["spec"]["replicas"], 1)

    def test_restores_after_capture_failure_even_with_measurement_guard_failure(self):
        service = {
            "metadata": {"uid": "uid", "labels": {LABEL: "true", "fulfillflow.io/http-run": "run"}},
            "spec": {
                "selector": {"matchLabels": {"app.kubernetes.io/name": "httpdiag-tracking"}},
                "replicas": 1,
            },
        }
        initial = copy.deepcopy(service)
        calls = []

        def kube(args, **kwargs):
            calls.append(args)
            if args[:2] in (["get", "service"], ["get", "deployment"]):
                return json.dumps(service)
            if args[:2] == ["get", "pods"]:
                return json.dumps(
                    {
                        "items": [
                            {
                                "metadata": {
                                    "uid": "old-pod",
                                    "labels": {"fulfillflow.io/http-run": "run"},
                                }
                            }
                        ]
                    }
                )
            if args[0] == "patch":
                ops = json.loads(args[-1])
                self.assertEqual(ops[0]["value"], service["metadata"]["uid"])
                self.assertEqual(ops[1]["value"], service["spec"]["replicas"])
                service["spec"]["replicas"] = ops[2]["value"]
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
                patch("scripts.http_trace_fault.await_no_pods", return_value={"remaining_pods": 0}),
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
