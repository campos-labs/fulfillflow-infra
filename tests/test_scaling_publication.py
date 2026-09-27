"""Publication checks must fail closed and never overwrite an existing reading."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / "docs/evidence/scaling/reproduce.py"
SPEC = importlib.util.spec_from_file_location("scaling_publication", SCRIPT)
publication = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publication)


class ScalingPublicationTests(unittest.TestCase):
    def test_corrupted_archive_is_rejected_before_statistics(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = {
                "files": [],
                "archives": [{"path": "damaged.zip", "sha256": "0" * 64}],
                "attempts": [],
            }
            (root / "manifest.json").write_text(json.dumps(manifest))
            (root / "comparison-summary.projection.json").write_text('{"results": []}')
            (root / "review.projection.json").write_text("{}")
            (root / "damaged.zip").write_bytes(b"damaged evidence")
            with patch.object(publication, "BASE", root):
                with self.assertRaisesRegex(ValueError, "ZIP hash"):
                    publication.read_evidence()

    def test_existing_output_is_preserved_without_reading_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "original.txt"
            marker.write_bytes(b"preserve")
            with patch("sys.argv", [str(SCRIPT), "--output", directory]):
                with patch.object(publication, "read_evidence") as read:
                    with self.assertRaisesRegex(ValueError, "Output must be a new directory"):
                        publication.main()
                    read.assert_not_called()
            self.assertEqual(marker.read_bytes(), b"preserve")
            self.assertEqual(list(Path(directory).iterdir()), [marker])

    def test_plots_require_explicit_new_destination(self):
        with patch("sys.argv", [str(SCRIPT), "--plots"]):
            with patch.object(publication, "read_evidence") as read:
                with self.assertRaisesRegex(ValueError, "--plots requires --output"):
                    publication.main()
                read.assert_not_called()


if __name__ == "__main__":
    unittest.main()
