"""Publication checks protect evidence selection and cumulative trace interpretation."""

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "observability_package", ROOT / "docs/evidence/observability/reproduce.py"
)
package = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(package)


class PublicationTests(unittest.TestCase):
    def test_cumulative_snapshots_count_only_current_phase(self):
        phases = package.verify_http_cases(package.BASE)
        self.assertEqual([p["spans"] for p in phases], [4, 3, 4])
        self.assertEqual([p["status"] for p in phases], [200, 503, 200])

    def test_changed_archive_is_rejected_without_rewriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "evidence"
            assets = Path(temporary) / "assets"
            shutil.copytree(package.BASE, base)
            shutil.copytree(package.ASSETS, assets)
            target = base / "archives/http.zip"
            altered = target.read_bytes() + b"unexpected trailing data"
            target.write_bytes(altered)
            with patch.object(package, "BASE", base), patch.object(package, "ASSETS", assets):
                with self.assertRaisesRegex(ValueError, "GENERATED_ARTIFACT_DIFFERS: http.zip"):
                    package.run()
            self.assertEqual(target.read_bytes(), altered)

    def test_changed_capture_fails_original_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "http"
            shutil.copytree(package.BASE / "http-05", base)
            target = base / "functional.json"
            target.write_bytes(target.read_bytes().replace(b'"status": 200', b'"status": 503'))
            with self.assertRaisesRegex(ValueError, "HTTP_HASH"):
                package.verify_http_manifest(base)

    def test_metadata_checkout_line_endings_do_not_change_package(self):
        expected = package.archive_bytes(package.members(package.BASE, "correlation"))
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "evidence"
            shutil.copytree(package.BASE, base)
            for name in (
                "manifest.json",
                "healthy-01-review.json",
                "pending-02-review.json",
                "discovery-01.json",
            ):
                target = base / name
                target.write_bytes(
                    target.read_text(encoding="utf-8").replace("\n", "\r\n").encode("utf-8")
                )
            actual = package.archive_bytes(package.members(base, "correlation"))
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
