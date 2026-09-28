import importlib.util
import io
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "check_kind_regression", ROOT / "scripts/azure/check_kind_regression.py"
)
regression = importlib.util.module_from_spec(spec)
spec.loader.exec_module(regression)


class IsolationTests(unittest.TestCase):
    def test_shared_base_change_is_not_ignored(self):
        self.assertFalse(regression.compare(b"replicas: 1\n", b"replicas: 2\n")["equal"])
        self.assertTrue(regression.compare(b"replicas: 1\r\n", b"replicas: 1\n")["equal"])

    def test_archive_traversal_and_links_are_rejected(self):
        for name, kind in (("k8s/../../escape", tarfile.REGTYPE), ("k8s/link", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                buffer = io.BytesIO()
                with tarfile.open(fileobj=buffer, mode="w") as archive:
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    item.linkname = "../../escape" if kind == tarfile.SYMTYPE else ""
                    archive.addfile(item)
                with self.assertRaises(ValueError):
                    regression.extract_tree(buffer.getvalue(), Path(folder))

    def test_candidate_has_no_account_specific_fields_or_approval(self):
        candidate = json.loads((ROOT / "config/aks-portability.json").read_text())
        self.assertFalse(candidate["provisioning_authorized"])
        serialized = json.dumps(candidate)
        for forbidden in (
            "subscription_id",
            "tenant_id",
            "quota_snapshot",
            "kubeconfig",
            "client_secret",
        ):
            self.assertNotIn(forbidden, serialized)
        self.assertFalse(candidate["state"]["reuse_previous_state"])
        self.assertEqual(candidate["state"]["roots"], ["bootstrap", "environment"])

    def test_aks_overlay_inherits_guards_without_modifying_workloads(self):
        tool = ROOT / ".tools/kubectl" / ("kubectl.exe" if os.name == "nt" else "kubectl")

        def render(profile):
            result = subprocess.run(
                [str(tool), "kustomize", str(ROOT / "k8s/overlays" / profile)],
                capture_output=True,
                check=True,
                timeout=45,
            )
            return list(yaml.safe_load_all(result.stdout))

        baseline, candidate = render("example"), render("aks-portability")
        self.assertEqual(len(baseline), len(candidate))

        def remove_environment_annotation(value):
            if isinstance(value, dict):
                if "fulfillflow.io/environment" in value:
                    self.assertEqual(
                        value.pop("fulfillflow.io/environment"), "aks-portability-candidate"
                    )
                for child in value.values():
                    remove_environment_annotation(child)
            elif isinstance(value, list):
                for child in value:
                    remove_environment_annotation(child)

        for document in candidate:
            self.assertEqual(
                document["metadata"]["annotations"]["fulfillflow.io/environment"],
                "aks-portability-candidate",
            )
            remove_environment_annotation(document)
        self.assertEqual(baseline, candidate)
