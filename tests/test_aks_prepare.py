import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "aks_prepare", ROOT / "scripts/azure/prepare_manifests.py"
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PrepareTests(unittest.TestCase):
    def setUp(self):
        self.registry = "synthetic.azurecr.io"
        self.image = self.registry + "/runtime@sha256:" + "a" * 64
        annotations = {
            "fulfillflow.io/validation-only": "true",
            "fulfillflow.io/deployment-blocked": "environment-and-image-provenance-not-approved",
        }
        self.document = {
            "kind": "Deployment",
            "metadata": {"name": "core", "annotations": annotations.copy()},
            "spec": {
                "template": {
                    "metadata": {"annotations": annotations.copy()},
                    "spec": {
                        "nodeSelector": {
                            "fulfillflow.io/deployment-approved": "example-never-schedule"
                        },
                        "containers": [{"name": "core", "image": "source"}],
                    },
                }
            },
        }

    def test_materialize_leaves_input_and_secrets_unchanged(self):
        result = module.materialize(
            [self.document], {"source": self.image}, "window-01", self.registry
        )[0]
        self.assertIn("nodeSelector", self.document["spec"]["template"]["spec"])
        self.assertNotIn("nodeSelector", result["spec"]["template"]["spec"])
        self.assertEqual(result["spec"]["template"]["spec"]["containers"][0]["image"], self.image)

    def test_placeholder_tag_and_foreign_registry_rejected(self):
        for image in (
            self.registry + "/runtime:latest",
            self.registry + "/runtime@sha256:" + "0" * 64,
            "other.azurecr.io/runtime@sha256:" + "a" * 64,
        ):
            with self.subTest(image=image), self.assertRaises(ValueError):
                module.materialize([self.document], {"source": image}, "window-01", self.registry)

    def test_missing_mapping_and_changed_guard_rejected(self):
        with self.assertRaises(ValueError):
            module.materialize([self.document], {"other": self.image}, "window-01", self.registry)
        self.document["spec"]["template"]["spec"]["nodeSelector"] = {"unexpected": "true"}
        with self.assertRaises(ValueError):
            module.materialize([self.document], {"source": self.image}, "window-01", self.registry)

    def test_secrets_rejected(self):
        with self.assertRaises(ValueError):
            module.materialize(
                [{"kind": "Secret"}], {"source": self.image}, "window-01", self.registry
            )

    def test_network_probes_share_destination_and_have_no_retry_or_credentials(self):
        for allowed in (True, False):
            job = module.network_probe(self.image, self.registry, "window-01", "10.0.0.21", allowed)
            self.assertEqual(job["spec"]["backoffLimit"], 0)
            pod = job["spec"]["template"]
            self.assertEqual(
                pod["metadata"]["labels"].get("fulfillflow.io/database-client") == "true", allowed
            )
            self.assertFalse(pod["spec"]["automountServiceAccountToken"])
            self.assertIn("10.0.0.21", pod["spec"]["containers"][0]["command"][-1])

    def test_public_or_loopback_probe_refused(self):
        for ip in ("8.8.8.8", "127.0.0.1", "0.0.0.0"):
            with self.subTest(ip=ip), self.assertRaises(ValueError):
                module.network_probe(self.image, self.registry, "window-01", ip, True)

    def test_generated_probe_program_distinguishes_timeout_from_refusal(self):
        import contextlib
        import errno
        import io
        from unittest.mock import Mock, patch

        job = module.network_probe(self.image, self.registry, "window-01", "10.0.0.21", False)
        program = job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
        for code, expected in ((errno.ETIMEDOUT, 0), (errno.ECONNREFUSED, 1), (0, 1)):
            client = Mock()
            client.connect_ex.return_value = code
            with (
                self.subTest(code=code),
                patch("socket.socket", return_value=client),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                with self.assertRaises(SystemExit) as result:
                    exec(compile(program, "network-probe", "exec"), {})
                self.assertEqual(result.exception.code, expected)
