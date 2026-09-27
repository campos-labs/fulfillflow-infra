"""Reject false trace joins, sensitive data and changes to the frozen deployment."""

import base64
import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.http_trace_contract import clone_api, verify_trace
from scripts.http_trace_pilot import Runner, validate_host
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
                "events": [{"name": "response_received"}, {"name": "response_validated"}]
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
