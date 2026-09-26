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

    def test_readiness_failure_names_component_and_preserves_status(self):
        with (
            patch(
                "scripts.scale_keda.k",
                side_effect=[RuntimeError("failed"), json.dumps({"items": []})],
            ),
            patch("scripts.scale_keda.get", return_value={"status": {"readyReplicas": 0}}),
            patch("scripts.scale_keda.write") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "KEDA_DEPLOYMENT_NOT_READY_keda-operator"):
                Pilot().wait_deployment(Path("private"), Path("output"), "keda-operator")
            self.assertEqual(save.call_args.args[1]["deployment_status"], {"readyReplicas": 0})

    def test_readiness_diagnostic_failure_preserves_original_failure(self):
        with (
            patch("scripts.scale_keda.k", side_effect=RuntimeError("failed")),
            patch("scripts.scale_keda.get", side_effect=RuntimeError("offline")),
            patch("scripts.scale_keda.write") as save,
        ):
            with self.assertRaisesRegex(RuntimeError, "KEDA_DEPLOYMENT_NOT_READY_keda-operator"):
                Pilot().wait_deployment(Path("private"), Path("output"), "keda-operator")
            self.assertTrue(save.call_args.args[1]["observation_unavailable"])

    def test_readiness_budget_exceeds_observed_restart_backoff(self):
        with patch("scripts.scale_keda.k") as command:
            Pilot().wait_deployment(Path("private"), Path("output"), "keda-operator")
            args = command.call_args.args
            self.assertIn("--timeout=420s", args[1])
            self.assertEqual(args[3], 430)

    def test_install_reuses_only_digest_pinned_images(self):
        import hashlib
        import tempfile

        import yaml

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / ".tools/keda/keda-2.20.2-core.yaml"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "kind": "Deployment",
                        "metadata": {"name": "keda-operator"},
                        "spec": {
                            "template": {
                                "spec": {
                                    "containers": [
                                        {"image": "old", "imagePullPolicy": "Always", "env": []}
                                    ]
                                }
                            }
                        },
                    }
                )
            )
            pilot = Pilot()
            pilot.pin["manifest_sha256"] = hashlib.sha256(manifest.read_bytes()).hexdigest()
            with (
                patch("scripts.scale_keda.env.ROOT", root),
                patch("scripts.scale_keda.get", return_value=None),
                patch("scripts.scale_keda.k", side_effect=RuntimeError("stop before mutation")),
            ):
                with self.assertRaisesRegex(RuntimeError, "stop before mutation"):
                    pilot.install(root, root)
            rendered = yaml.safe_load((root / "keda-install.yaml").read_text())
            container = rendered["spec"]["template"]["spec"]["containers"][0]
            self.assertEqual(container["imagePullPolicy"], "IfNotPresent")
            self.assertEqual(container["image"], pilot.pin["images"]["keda-operator"])
            self.assertIn("@sha256:", container["image"])


class CapacityPilotTests(unittest.TestCase):
    def test_capacity_profile_preserves_policy_and_baseline(self):
        from scripts.scale_contract import schedule

        base = {
            "stages": [
                {"seconds": 15, "rate": 2},
                {"seconds": 30, "rate": 8},
                {"seconds": 15, "rate": 2},
            ],
            "replicas": [1, 2],
            "http_concurrency": 8,
            "functional_deadline_seconds": 60,
        }
        pilot = Pilot(capacity_profile=True)
        result = pilot.capacity_settings(base)
        self.assertEqual(len(schedule(result["stages"], characterization=True)), 540)
        self.assertEqual(result["replicas"], [1])
        self.assertEqual(result["http_concurrency"], 16)
        self.assertEqual(result["functional_deadline_seconds"], 60)
        self.assertEqual(base["stages"][1]["rate"], 8)
        self.assertEqual(scaled_object(pilot.pin), scaled_object(Pilot().pin))

    def test_capacity_requires_control_and_disallows_fixed_or_changed_profile(self):
        from scripts.scale_calibration import _execute

        good = dict(
            extension=Pilot(capacity_profile=True),
            controlled_host=True,
            reuse_terminal_reads=True,
            peak_rate=16,
            http_concurrency=16,
        )
        for override in (
            {"controlled_host": False},
            {"reuse_terminal_reads": False},
            {"peak_rate": 12},
            {"http_concurrency": 8},
            {"plateau_seconds": 45},
            {"fixed_replicas": 2},
            {"diagnostic": True},
        ):
            with (
                self.subTest(override=override),
                patch("scripts.scale_calibration.identity") as identity,
            ):
                with self.assertRaisesRegex(RuntimeError, "ADAPTIVE_CAPACITY_PROFILE_NOT_ALLOWED"):
                    _execute(Path("unused"), Path("unused-output"), **{**good, **override})
                identity.assert_not_called()

    def test_capacity_load_uses_same_http_capture_and_reuse_and_stops_on_failure(self):
        pilot = Pilot(capacity_profile=True)
        with (
            patch.object(pilot, "install"),
            patch.object(pilot, "metric_probe"),
            patch("scripts.scale_keda.write"),
            patch("scripts.scale_diagnostic.wait_throttling"),
            patch("scripts.scale_keda.calibration.run_one", return_value=False) as run,
        ):
            with self.assertRaisesRegex(RuntimeError, "ADAPTIVE_FUNCTIONAL"):
                pilot.run(Path("private"), Path("output"), {}, {}, "base", {}, 123)
            self.assertEqual(run.call_args.args[1], Path("output/adaptive"))
            self.assertEqual(run.call_args.args[2], 1)
            self.assertIs(run.call_args.kwargs["policy"], pilot)
            self.assertTrue(run.call_args.kwargs["diagnostic"])
            self.assertTrue(run.call_args.kwargs["reuse_terminal_reads"])
