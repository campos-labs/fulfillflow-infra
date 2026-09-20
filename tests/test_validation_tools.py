import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


validation = load("validate")
setup = load("setup_validation_tools")


class ValidationTests(unittest.TestCase):
    def test_rendered_manifest_hash_matches_delivered_bytes(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "manifest.yaml"
            digest = validation.save_manifest(path, "kind: Namespace\n# configuração\n")
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertNotIn(b"\r\n", path.read_bytes())

    def test_download_corruption_rejected(self):
        digest = hashlib.sha256(b"expected").hexdigest()
        with self.assertRaisesRegex(ValueError, "checksum"):
            setup.verified_payload(b"corrupt", digest)
        self.assertEqual(setup.verified_payload(b"expected", digest), b"expected")

    def test_schema_identity_is_confined(self):
        self.assertEqual(
            validation.schema_name({"kind": "Deployment", "apiVersion": "apps/v1"}),
            "deployment-apps-v1.json",
        )
        self.assertEqual(
            validation.schema_name({"kind": "NetworkPolicy", "apiVersion": "networking.k8s.io/v1"}),
            "networkpolicy-networking-v1.json",
        )
        with self.assertRaises(ValueError):
            validation.schema_name({"kind": "../../other", "apiVersion": "v1"})

    def test_existing_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "existing"
            target.mkdir()
            marker = target / "keep.txt"
            marker.write_text("original", encoding="utf-8")
            versions = [
                json.dumps(
                    {"clientVersion": {"gitVersion": "v1.35.3"}, "kustomizeVersion": "v5.7.1"}
                ),
                json.dumps({"terraform_version": "1.13.5"}),
            ]
            with (
                patch.object(validation, "run", side_effect=versions),
                self.assertRaises(FileExistsError),
            ):
                validation.validate(Path("kubectl"), Path("terraform"), target)
            self.assertEqual(marker.read_text(), "original")

    def test_child_exit_is_failure(self):
        with self.assertRaisesRegex(RuntimeError, "exit 7"):
            validation.run([sys.executable, "-c", "raise SystemExit(7)"])

    def test_powershell_propagates_child_exit_with_space_paths(self):
        pwsh = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
        self.assertTrue(pwsh, "Set PWSH_PATH to test the real PowerShell launcher")
        with tempfile.TemporaryDirectory(prefix="infra validation ") as temp:
            root = Path(temp)
            launcher = root / "Invoke-Validation.ps1"
            shutil.copyfile(ROOT / "scripts/Invoke-Validation.ps1", launcher)
            (root / "validate.py").write_text(
                "import sys\nfrom pathlib import Path\n"
                "assert '--output' in sys.argv\n"
                "Path(sys.argv[sys.argv.index('--output')+1]).write_text('called once')\n"
                "raise SystemExit(7)\n",
                encoding="utf-8",
            )
            output = root / "output with spaces.txt"
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(launcher),
                    "-Python",
                    sys.executable,
                    "-OutputDirectory",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertEqual(output.read_text(), "called once")


if __name__ == "__main__":
    unittest.main()
