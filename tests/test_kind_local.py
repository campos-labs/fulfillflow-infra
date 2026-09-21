"""Verify the local overlay cannot silently claim or use Azure infrastructure."""

import os
import subprocess
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class LocalOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        k = os.environ.get("KUBECTL") or str(
            ROOT / ".tools/kubectl" / ("kubectl.exe" if os.name == "nt" else "kubectl")
        )
        cls.docs = list(
            yaml.safe_load_all(
                subprocess.check_output(
                    [k, "kustomize", str(ROOT / "k8s/overlays/kind-local")],
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                )
            )
        )

    def test_cluster_is_loopback_and_node_image_is_pinned(self):
        cfg = yaml.safe_load((ROOT / "config/kind-local.yaml").read_text())
        self.assertEqual(cfg["networking"]["apiServerAddress"], "127.0.0.1")
        self.assertEqual(len(cfg["nodes"]), 1)
        self.assertIn("@sha256:", cfg["nodes"][0]["image"])
        self.assertNotIn("extraMounts", cfg["nodes"][0])

    def test_local_storage_retains_and_never_calls_azure_csi(self):
        sc = next(x for x in self.docs if x["kind"] == "StorageClass")
        self.assertEqual(sc["provisioner"], "rancher.io/local-path")
        self.assertEqual(sc["reclaimPolicy"], "Retain")
        self.assertNotIn("parameters", sc)
        self.assertFalse(sc["allowVolumeExpansion"])

    def test_no_secrets_or_public_services_in_overlay(self):
        self.assertFalse(any(x["kind"] == "Secret" for x in self.docs))
        for x in self.docs:
            if x["kind"] == "Service":
                self.assertIn(x["spec"].get("type", "ClusterIP"), ["ClusterIP"])

    def test_runtime_is_local_only_with_preserved_ownership(self):
        deployments = [x for x in self.docs if x["kind"] == "Deployment"]
        self.assertEqual(len(deployments), 6)
        for x in deployments + [x for x in self.docs if x["kind"] == "Job"]:
            self.assertEqual(
                x["metadata"]["annotations"]["fulfillflow.io/environment"], "kind-local-only"
            )
            spec = x["spec"]["template"]["spec"]
            self.assertFalse(spec["automountServiceAccountToken"])
            container = spec["containers"][0]
            self.assertEqual(container["image"], "fulfillflow-kind-runtime:source-9e3a135a00db")
            self.assertEqual(container["imagePullPolicy"], "Never")
            self.assertTrue(container["securityContext"]["readOnlyRootFilesystem"])
            self.assertTrue(
                any(
                    e["name"] == "DATABASE_URL" and "secretKeyRef" in e["valueFrom"]
                    for e in container["env"]
                )
            )

    def test_cpu_budget_and_policies_are_preserved(self):
        total = 0
        for x in self.docs:
            if x["kind"] in ("Deployment", "StatefulSet"):
                cpu = x["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["cpu"]
                total += int(cpu[:-1]) if cpu.endswith("m") else int(cpu) * 1000
        self.assertEqual(total, 1900)
        self.assertEqual(len([x for x in self.docs if x["kind"] == "NetworkPolicy"]), 13)


if __name__ == "__main__":
    unittest.main()
