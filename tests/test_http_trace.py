"""Reject false trace joins, sensitive data and changes to the frozen deployment."""

import base64
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts.http_trace_contract import ci_verdict, clone_api, verify_trace
from scripts.http_trace_pilot import Runner, sink, validate_host
from scripts.http_trace_receiver import project


def payload():
    return {
        "resource_spans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"string_value": "httpdiag-core"}}
                    ]
                },
                "scope_spans": [
                    {
                        "spans": [
                            {
                                "name": "GET /api/v1/carrier-events",
                                "trace_id": base64.b64encode(bytes(range(16))).decode(),
                                "span_id": base64.b64encode(bytes(range(8))).decode(),
                                "kind": "SPAN_KIND_SERVER",
                                "start_time_unix_nano": "100",
                                "end_time_unix_nano": "200",
                                "attributes": [
                                    {
                                        "key": "http.route",
                                        "value": {"string_value": "/api/v1/carrier-events"},
                                    },
                                    {
                                        "key": "http.request.method",
                                        "value": {"string_value": "GET"},
                                    },
                                    {
                                        "key": "http.response.status_code",
                                        "value": {"int_value": "200"},
                                    },
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }


def chain():
    rows = []
    for i, (service, kind) in enumerate(
        (("observer", "CLIENT"), ("core", "SERVER"), ("core", "CLIENT"), ("tracking", "SERVER"))
    ):
        rows.append(
            {
                "service": "httpdiag-" + service,
                "kind": "SPAN_KIND_" + kind,
                "trace_id": "a" * 32,
                "span_id": str(i),
                "parent_span_id": str(i - 1) if i else None,
                "start_time_unix_nano": "100",
                "end_time_unix_nano": "200",
                "attributes": {
                    "http.response.status_code": "200",
                    "http.request.method": "GET",
                    "http.route": "/api/v1/carrier-events"
                    if i < 2
                    else "/internal/v1/tracking/carrier-events",
                },
                "events": [{"name": "response_received"}, {"name": "content_type_validated"}]
                if i == 2
                else [],
            }
        )
    return {"records": rows, "accepted_batches": 3, "rejected_batches": 0}, {
        "complete": True,
        "query_count": 1,
        "request_id_echoed": True,
        "trace_id": "a" * 32,
    }


class TraceContracts(unittest.TestCase):
    def test_receiver_meets_restricted_pod_security(self):
        spec = sink("image")["spec"]["template"]["spec"]
        self.assertEqual(spec["securityContext"]["seccompProfile"], {"type": "RuntimeDefault"})
        self.assertTrue(spec["securityContext"]["runAsNonRoot"])
        security = spec["containers"][0]["securityContext"]
        self.assertFalse(security["allowPrivilegeEscalation"])
        self.assertEqual(security["capabilities"]["drop"], ["ALL"])

    def test_command_failure_preserves_stage_without_raw_diagnostics(self):
        process = Mock()
        process.communicate.return_value = ("private stdout", "timed out waiting; secret stderr")
        process.returncode = 1
        process.poll.return_value = 1
        with tempfile.TemporaryDirectory() as directory:
            runner = Runner(Path(directory), Path(directory))
            runner.stage = "rollout_httpdiag-sink"
            with (
                patch.object(runner, "check"),
                patch("scripts.http_trace_pilot.env.executable", return_value="kubectl"),
                patch("scripts.http_trace_pilot.subprocess.Popen", return_value=process),
            ):
                with self.assertRaisesRegex(RuntimeError, "COMMAND_FAILED_KUBECTL"):
                    runner.command(["kubectl", "rollout", "status"])
        self.assertEqual(
            runner.command_failures,
            [
                {
                    "stage": "rollout_httpdiag-sink",
                    "tool": "kubectl",
                    "returncode": 1,
                    "reason": "ROLLOUT_DEADLINE",
                }
            ],
        )
        self.assertFalse(runner.query_started)

    def test_ci_waits_and_rejects_failure_or_a_different_reference(self):
        self.assertFalse(ci_verdict({"status": "in_progress", "headSha": "expected"}, "expected"))
        self.assertTrue(
            ci_verdict(
                {"status": "completed", "headSha": "expected", "conclusion": "success"}, "expected"
            )
        )
        for record in (
            {"status": "completed", "headSha": "other", "conclusion": "success"},
            {"status": "completed", "headSha": "expected", "conclusion": "failure"},
            {"status": "unknown", "headSha": "expected"},
        ):
            with self.assertRaises(RuntimeError):
                ci_verdict(record, "expected")

    def test_memory_and_power_are_independent_guards(self):
        validate_host({"available_gib": 5, "required_gib": 5, "power_plugged": True})
        for available, plugged, error in ((4.99, True, "MEMORY"), (8, False, "BATTERY")):
            with self.assertRaisesRegex(RuntimeError, error):
                validate_host(
                    {"available_gib": available, "required_gib": 5, "power_plugged": plugged}
                )

    def test_failing_runtime_sample_is_preserved_before_cleanup(self):
        runner = Runner(Path("private"), Path("output"))
        sample = {"available_gib": 1.9, "required_gib": 2, "power_plugged": True}
        with patch("scripts.http_trace_pilot.host_snapshot", return_value=sample):
            with self.assertRaisesRegex(RuntimeError, "MEMORY"):
                runner.check()
        self.assertEqual(runner.samples, [sample])

    def test_otlp_binary_ids_are_normalized_for_observer_join(self):
        (row,) = project(payload())
        self.assertEqual(row["trace_id"], bytes(range(16)).hex())

    def test_sensitive_attribute_is_rejected_not_retained(self):
        value = payload()
        value["resource_spans"][0]["scope_spans"][0]["spans"][0]["attributes"].append(
            {"key": "http.request.header.authorization", "value": {"string_value": "secret"}}
        )
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_ATTRIBUTE"):
            project(value)

    def test_raw_exception_event_is_rejected(self):
        value = payload()
        value["resource_spans"][0]["scope_spans"][0]["spans"][0]["events"] = [
            {"name": "exception", "attributes": []}
        ]
        with self.assertRaisesRegex(ValueError, "UNEXPECTED_EVENT"):
            project(value)

    def test_chain_requires_all_roles_and_independent_result(self):
        snapshot, result = chain()
        self.assertTrue(verify_trace(snapshot, result)["complete"])
        for defect in ("parent", "missing", "duplicate", "rejection", "validation", "functional"):
            with self.subTest(defect=defect):
                snap, res = copy.deepcopy(snapshot), copy.deepcopy(result)
                if defect == "parent":
                    snap["records"][2]["parent_span_id"] = "0"
                if defect == "missing":
                    snap["records"].pop()
                if defect == "duplicate":
                    snap["records"].append(snap["records"][0])
                if defect == "rejection":
                    snap["rejected_batches"] = 1
                if defect == "validation":
                    snap["records"][2]["events"] = []
                if defect == "functional":
                    res["complete"] = False
                with self.assertRaises(ValueError):
                    verify_trace(snap, res)

    def test_clones_route_both_directions_inside_the_diagnostic_pair(self):
        for role, key, historical, target in (
            ("core", "TRACKING_BASE_URL", "http://tracking:8000", "http://httpdiag-tracking:8000"),
            ("tracking", "CORE_BASE_URL", "http://core:8000", "http://httpdiag-core:8000"),
        ):
            with self.subTest(role=role):
                source = {
                    "metadata": {"name": role},
                    "spec": {
                        "replicas": 0,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "name": role,
                                        "env": [
                                            {"name": key, "value": historical},
                                            {
                                                "name": "INTERNAL_API_SECRET",
                                                "valueFrom": {
                                                    "secretKeyRef": {"name": role, "key": "secret"}
                                                },
                                            },
                                        ],
                                    }
                                ]
                            }
                        },
                    },
                }
                before = copy.deepcopy(source)
                clone = clone_api(source, role, "diagnostic-image")
                values = clone["spec"]["template"]["spec"]["containers"][0]["env"]
                self.assertEqual(
                    [v for v in values if v["name"] == key], [{"name": key, "value": target}]
                )
                self.assertEqual(
                    [v for v in values if v["name"] == "INTERNAL_API_SECRET"],
                    [before["spec"]["template"]["spec"]["containers"][0]["env"][1]],
                )
                self.assertEqual(source, before)
                self.assertEqual(clone["spec"]["replicas"], 1)

    def test_cloning_preserves_original_and_db_owner(self):
        source = {
            "metadata": {"name": "core"},
            "spec": {
                "replicas": 1,
                "selector": {},
                "template": {
                    "metadata": {},
                    "spec": {
                        "containers": [
                            {
                                "name": "core",
                                "image": "frozen",
                                "env": [
                                    {
                                        "name": "DATABASE_URL",
                                        "valueFrom": {
                                            "secretKeyRef": {"name": "core-database", "key": "url"}
                                        },
                                    }
                                ],
                            }
                        ]
                    },
                },
            },
        }
        original = copy.deepcopy(source)
        clone = clone_api(source, "core", "new-reference")
        self.assertEqual(source, original)
        container = clone["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(
            container["env"][0], original["spec"]["template"]["spec"]["containers"][0]["env"][0]
        )
        self.assertEqual(container["image"], "new-reference")
        self.assertNotEqual(clone["spec"]["selector"], source["spec"]["selector"])


if __name__ == "__main__":
    unittest.main()
