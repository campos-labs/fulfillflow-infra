import copy
import unittest

from scripts.azure.prepare_http_trace import gate, prepare


class HttpPreparationTests(unittest.TestCase):
    def setUp(self):
        self.record = dict.fromkeys(
            (
                "window_authorized",
                "healthy_extension_authorized",
                "basic_acceptance_complete",
                "evidence_preserved",
                "no_pending_issue",
                "cost_within_authorized_limit",
                "no_new_azure_resources_or_roles",
                "capacity_verified",
                "prepared_and_reviewed",
            ),
            True,
        )
        self.record["elapsed_seconds"] = 15300

    def test_exact_boundary_and_no_fault_permission(self):
        self.assertTrue(gate(self.record)["eligible"])
        self.assertFalse(gate(self.record)["fault_authorized"])
        self.assertFalse(gate({**self.record, "elapsed_seconds": 15301})["eligible"])

    def test_every_condition_required(self):
        for key in self.record:
            with self.subTest(key=key):
                value = None if key == "elapsed_seconds" else False
                self.assertFalse(gate({**self.record, key: value})["eligible"])

    def test_clock_must_be_finite_nonnegative(self):
        for value in (float("nan"), float("inf"), -1, True, "0"):
            self.assertFalse(gate({**self.record, "elapsed_seconds": value})["eligible"])

    def source(self, role):
        return {
            "kind": "Deployment",
            "metadata": {
                "name": role,
                "namespace": "fulfillflow",
                "labels": {"fulfillflow.io/window": "test-window"},
            },
            "spec": {
                "template": {
                    "metadata": {},
                    "spec": {"containers": [{"name": role, "image": "original"}]},
                }
            },
        }

    def test_clones_preserve_originals_and_route_to_each_other(self):
        runtime = [self.source(r) for r in ("core", "tracking")]
        original = copy.deepcopy(runtime)
        result = prepare(
            runtime,
            "synthetic.azurecr.io/runtime@sha256:" + "a" * 64,
            "synthetic.azurecr.io",
            "test-window",
        )
        self.assertEqual(runtime, original)
        self.assertEqual(len(result), 8)
        deployments = [d for d in result if d["kind"] == "Deployment"]
        self.assertEqual(
            {d["metadata"]["name"] for d in deployments},
            {"httpdiag-core", "httpdiag-tracking", "httpdiag-sink"},
        )
        for d in deployments:
            self.assertEqual(
                d["spec"]["template"]["spec"]["containers"][0]["imagePullPolicy"], "IfNotPresent"
            )
        self.assertTrue(all(d["metadata"]["namespace"] == "fulfillflow" for d in result))

    def test_wrong_window_rejected(self):
        with self.assertRaises(ValueError):
            prepare(
                [self.source("core"), self.source("tracking")],
                "synthetic.azurecr.io/runtime@sha256:" + "a" * 64,
                "synthetic.azurecr.io",
                "other",
            )
