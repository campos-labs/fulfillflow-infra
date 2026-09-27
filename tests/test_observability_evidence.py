"""Offline evidence checks reject tampering and false joins without local artifacts."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from scripts import verify_observability_evidence as evidence


class EvidenceTests(unittest.TestCase):
    def test_published_selection_is_self_contained(self):
        result = evidence.verify()
        self.assertEqual(len(result["cases"]), 2)
        self.assertFalse(result["load_executed"])

    def test_changed_bytes_fail_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            shutil.copytree(evidence.ROOT, target)
            path = target / "records/healthy-01/functional.json"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "EVIDENCE_HASH"):
                evidence.verify(target)

    def test_join_rejects_unrelated_request_even_when_directly_reviewed(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "evidence"
            shutil.copytree(evidence.ROOT, target)
            path = target / "records/pending-02/worker-records.json"
            value = json.loads(path.read_bytes())
            value["notifications-worker"]["records"][-1]["request_id"] = "unrelated"
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "CORRELATION_MISMATCH"):
                evidence.verify_case(target, "pending-02")


if __name__ == "__main__":
    unittest.main()
