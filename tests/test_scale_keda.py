"""Policy bounds, missing metrics and safe ownership without a live cluster."""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.scale_keda import CONFIG, Pilot, quantity, scaled_object


class KedaContracts(unittest.TestCase):
    def test_policy_uses_aged_durable_work_and_no_fallback(self):
        spec = scaled_object(json.loads(CONFIG.read_text()))["spec"]
        self.assertEqual((spec["minReplicaCount"], spec["maxReplicaCount"]), (1, 2))
        self.assertNotIn("fallback", spec)
        trigger = spec["triggers"][0]
        self.assertEqual(trigger["metricType"], "AverageValue")
        self.assertEqual(trigger["metadata"]["targetQueryValue"], "1")
        self.assertIn("interval '5 seconds'", trigger["metadata"]["query"])
        self.assertIn("next_attempt_at <= now()", trigger["metadata"]["query"])
        self.assertEqual(
            spec["advanced"]["horizontalPodAutoscalerConfig"]["behavior"]["scaleDown"][
                "stabilizationWindowSeconds"
            ],
            300,
        )

    def test_quantity_rejects_unusable_metric(self):
        self.assertEqual(quantity("1250m"), 1.25)
        self.assertEqual(quantity("0"), 0)
        for value in ("NaN", "inf", "-1", "invalid"):
            with self.assertRaises(ValueError):
                quantity(value)

    def test_missing_metric_is_unavailable_not_zero(self):
        pilot = Pilot()
        pilot.object_uid = "ours"
        obj = {"metadata": {"uid": "ours"}, "status": {}}
        with patch("scripts.scale_keda.get", side_effect=[obj, None]):
            sample = pilot.status(Path("unused"))
        self.assertEqual(sample["metric"], {"available": False})

    def test_cleanup_refuses_foreign_controller(self):
        pilot = Pilot()
        foreign = {"metadata": {"uid": "other", "labels": {}}}
        with (
            patch("scripts.scale_keda.get", return_value=foreign),
            patch("scripts.scale_keda.k") as command,
        ):
            with self.assertRaisesRegex(RuntimeError, "CLEANUP_CONTROLLER_IDENTITY"):
                pilot.cleanup(Path("unused"))
            command.assert_not_called()

    def test_no_manual_scale_while_hpa_remains(self):
        with (
            patch("scripts.scale_keda.get", side_effect=[None, {"metadata": {"name": "hpa"}}]),
            patch("scripts.scale_keda.k") as command,
        ):
            with self.assertRaisesRegex(RuntimeError, "HPA_STILL_PRESENT"):
                Pilot().cleanup(Path("unused"))
            command.assert_not_called()

    def test_cleanup_refuses_differently_named_target_hpa(self):
        hpa = {"spec": {"scaleTargetRef": {"name": "core-worker"}}}
        with (
            patch("scripts.scale_keda.get", return_value=None),
            patch("scripts.scale_keda.k", return_value=json.dumps({"items": [hpa]})) as command,
        ):
            with self.assertRaisesRegex(RuntimeError, "FOREIGN_TARGET_HPA"):
                Pilot().cleanup(Path("unused"))
            self.assertEqual(command.call_count, 1)

    def test_attribution_allows_prior_restarts_but_rejects_new_restart(self):
        pilot = Pilot()
        pilot.restart_baseline = {"pod": 2}
        pilot.pods = {"pod": {"name": "worker", "restarts": 2}}
        pilot.logs = {"record": {"request_id": "r", "pod_uid": "pod"}}
        with patch.object(pilot, "sample"), patch("scripts.scale_keda.write"):
            self.assertTrue(
                pilot.attribution(Path("unused"), {"event": {"request_id": "r"}}, Path("unused"))[
                    "complete"
                ]
            )
            pilot.pods["pod"]["restarts"] = 3
            self.assertFalse(
                pilot.attribution(Path("unused"), {"event": {"request_id": "r"}}, Path("unused"))[
                    "complete"
                ]
            )

    def test_multinamespace_bundle_does_not_force_application_namespace(self):
        from scripts.scale_keda import k

        with (
            patch("scripts.scale_keda.env.tools", return_value=("kubectl", None)),
            patch("scripts.scale_keda.env.command") as command,
        ):
            k(Path("private"), ["apply", "-f", "-"], namespace=None, data="manifest")
            self.assertNotIn("-n", command.call_args.args[0])
