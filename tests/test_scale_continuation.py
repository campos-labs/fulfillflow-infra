"""Continuation never replaces outcomes or restarts an ambiguous attempt."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import scale_continuation as c


class ContinuationTests(unittest.TestCase):
    def test_order_is_original_and_has_nine_unique_positions(self):
        self.assertEqual(c.names()[0:3], ["b1-p1-adaptive", "b1-p2-fixed-2", "b1-p3-fixed-1"])
        self.assertEqual(len(set(c.names())), 9)

    def memory(self, samples, *, active="", ac=True, deadline=200):
        now = [0.0]
        values = iter(samples)
        last = [samples[-1]]

        def sample():
            last[0] = next(values, last[0])
            return {"host_available_bytes": last[0] * 2**30, "power_plugged": ac}

        def sleep(n):
            now[0] += n

        log = Path(self.tmp.name) / "memory.jsonl"
        c.wait_memory(
            log,
            deadline,
            sample=sample,
            command=Mock(return_value=active),
            clock=lambda: now[0],
            sleep=sleep,
        )
        return now[0], [json.loads(x) for x in log.read_text().splitlines()]

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_wait_requires_three_consecutive_healthy_samples(self):
        elapsed, rows = self.memory([5.2, 4.9, 5.1, 5.3, 5.2])
        self.assertEqual(elapsed, 20)
        self.assertEqual(len(rows), 5)

    def test_wait_is_bounded_and_preserves_low_values(self):
        with self.assertRaisesRegex(RuntimeError, "WAIT_EXHAUSTED"):
            self.memory([4.9])
        rows = (Path(self.tmp.name) / "memory.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 36)

    def test_session_budget_precedes_wait_budget(self):
        with self.assertRaisesRegex(RuntimeError, "WAIT_EXHAUSTED"):
            self.memory([5.2], deadline=9)

    def test_running_container_refused_without_stop(self):
        with self.assertRaisesRegex(RuntimeError, "HOST_NOT_IDLE"):
            self.memory([6], active="foreign")

    def test_unplugged_refused(self):
        with self.assertRaisesRegex(RuntimeError, "AC_UNCONFIRMED"):
            self.memory([6], ac=False)

    def test_inventory_reports_interrupted_and_incomplete_blocks(self):
        rows = [{"attempt": n, "session": "same"} for n in c.names()]
        out = c.summary(rows)
        self.assertFalse(out["blocks"][0]["continuous"])
        self.assertTrue(out["blocks"][1]["continuous"])
        rows[4]["session"] = "other"
        self.assertFalse(c.summary(rows)["blocks"][1]["continuous"])
        self.assertFalse(c.summary(rows[:4])["blocks"][1]["continuous"])

    def test_changed_measurement_rejected(self):
        with patch.object(
            c.cmp.env,
            "command",
            side_effect=["scripts/scale_comparison.py", "scripts/scale_comparison.py", "diff"],
        ):
            with self.assertRaisesRegex(RuntimeError, "QUALIFIED_MEASUREMENT_CHANGED"):
                c.verify_measurement()

    def test_added_runtime_rejected(self):
        with patch.object(
            c.cmp.env,
            "command",
            side_effect=[
                "scripts/scale_comparison.py",
                "scripts/scale_comparison.py\nscripts/new_runtime.py",
            ],
        ):
            with self.assertRaisesRegex(RuntimeError, "UNREVIEWED_MEASUREMENT_FILES"):
                c.verify_measurement()

    def test_original_runtime_can_be_reused_with_new_coordinator(self):
        with patch.object(
            c.cmp.env,
            "command",
            side_effect=[
                "scripts/scale_comparison.py",
                "scripts/scale_comparison.py\nscripts/scale_continuation.py",
                "",
            ],
        ):
            self.assertEqual(c.verify_measurement(), 1)

    def bundle(self):
        p = Path(self.tmp.name) / "bundle"
        p.mkdir()
        r = {
            "execution_valid": True,
            "shutdown_confirmed": True,
            "host_conditions_valid": True,
            "protocol_sha256": c.cmp.digest(c.cmp.CONFIG),
            "condition": "adaptive",
            "counts": {"completed_late": 354},
        }
        for name, data in [
            ("comparison-result.json", r),
            ("summary.json", {}),
            ("shutdown.json", {}),
            ("protocol.json", {}),
        ]:
            (p / name).write_text(json.dumps(data))
        (p / "checksums.sha256").write_text(
            "".join(
                hashlib.sha256(x.read_bytes()).hexdigest() + "  " + x.name + "\n"
                for x in p.iterdir()
            )
        )
        return p

    def test_late_result_retained_and_tamper_rejected(self):
        p = self.bundle()
        self.assertEqual(c.verify_bundle(p)["counts"]["completed_late"], 354)
        (p / "summary.json").write_text("changed")
        with self.assertRaisesRegex(RuntimeError, "HASH_MISMATCH"):
            c.verify_bundle(p)

    def test_manifest_cannot_escape_directory(self):
        p = self.bundle()
        (p / "checksums.sha256").write_text("abc  ../secret\n")
        with self.assertRaisesRegex(RuntimeError, "INVALID_EVIDENCE_MANIFEST"):
            c.verify_bundle(p)

    def test_unfinished_attempt_is_not_retried(self):
        output = Path(self.tmp.name) / "out"
        (output / "starts").mkdir(parents=True)
        (output / "starts" / (c.names()[1] + ".json")).write_text("{}")
        with patch.object(c, "verify_bundle", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "UNFINISHED_ATTEMPT"):
                c.completed(Path("source"), output)

    def test_noncontiguous_attempts_refused(self):
        output = Path(self.tmp.name) / "out"
        (output / "attempts" / c.names()[2]).mkdir(parents=True)
        with patch.object(c, "verify_bundle", return_value={}):
            with self.assertRaisesRegex(RuntimeError, "NONCONTIGUOUS"):
                c.completed(Path("source"), output)

    def test_preflight_failure_does_not_create_attempt_start(self):
        output = Path(self.tmp.name) / "out"
        private = Path(self.tmp.name) / "private"
        private.mkdir()
        initial = [{"attempt": c.names()[0]}]
        with (
            patch.object(c.cmp, "require_context"),
            patch.object(c.cmp.env, "command", return_value=""),
            patch.object(c, "manifest", return_value={}),
            patch.object(c, "completed", return_value=initial),
            patch.object(c, "wait_memory", side_effect=RuntimeError("WAIT_EXHAUSTED")),
            patch.object(c.cmp, "one") as one,
        ):
            with self.assertRaisesRegex(RuntimeError, "WAIT_EXHAUSTED"):
                c.run(private, Path("source"), output, "execute")
            one.assert_not_called()
        self.assertEqual(list((output / "starts").iterdir()), [])
        self.assertFalse((private / "comparison-continuation.lock").exists())
        self.assertEqual(len(list((output / "sessions").glob("*/stop.json"))), 1)

    def test_check_never_runs_load(self):
        private = Path(self.tmp.name) / "private"
        private.mkdir()
        with (
            patch.object(c.cmp, "require_context"),
            patch.object(c.cmp.env, "command", return_value=""),
            patch.object(c, "manifest", return_value={}),
            patch.object(c, "completed", return_value=[{}]),
            patch.object(c.cmp, "one") as one,
        ):
            c.run(private, Path("source"), Path(self.tmp.name) / "out", "check")
            one.assert_not_called()

    def test_eight_remaining_positions_run_once_and_summary_retains_first(self):
        output = Path(self.tmp.name) / "out"
        private = Path(self.tmp.name) / "private"
        private.mkdir()

        def result(folder):
            return {"condition": folder.name.split("-", 2)[2], "counts": {"completed_late": 354}}

        def execute(private, folder, condition):
            folder.mkdir()

        with (
            patch.object(c.cmp, "require_context"),
            patch.object(c.cmp.env, "command", return_value=""),
            patch.object(c, "manifest", return_value={}),
            patch.object(c, "verify_bundle", side_effect=result),
            patch.object(c, "verify_measurement"),
            patch.object(c, "wait_memory"),
            patch.object(c.cmp, "one", side_effect=execute) as one,
        ):
            c.run(private, Path("source"), output, "execute")
            self.assertEqual([call.args[1].name for call in one.call_args_list], c.names()[1:])
            saved = c.read(output / "comparison-summary.json")
            self.assertTrue(saved["complete"])
            self.assertEqual(saved["results"][0]["session"], "original-interrupted")
            self.assertEqual(saved["results"][0]["result"]["counts"]["completed_late"], 354)
            with self.assertRaisesRegex(RuntimeError, "ALREADY_COMPLETE"):
                c.run(private, Path("source"), output, "execute")
            self.assertEqual(one.call_count, 8)

    def test_wait_pause_resumes_remaining_prefix_without_repeating(self):
        output = Path(self.tmp.name) / "out"
        private = Path(self.tmp.name) / "private"
        private.mkdir()

        def result(folder):
            return {"condition": folder.name.split("-", 2)[2]}

        def execute(private, folder, condition):
            folder.mkdir()

        with (
            patch.object(c.cmp, "require_context"),
            patch.object(c.cmp.env, "command", return_value=""),
            patch.object(c, "manifest", return_value={}),
            patch.object(c, "verify_bundle", side_effect=result),
            patch.object(c, "verify_measurement"),
            patch.object(c, "wait_memory", side_effect=[None, RuntimeError("WAIT_EXHAUSTED")]),
        ):
            with patch.object(c.cmp, "one", side_effect=execute) as first:
                with self.assertRaisesRegex(RuntimeError, "WAIT_EXHAUSTED"):
                    c.run(private, Path("source"), output, "execute")
                self.assertEqual(first.call_count, 1)
        with (
            patch.object(c.cmp, "require_context"),
            patch.object(c.cmp.env, "command", return_value=""),
            patch.object(c, "manifest", return_value={}),
            patch.object(c, "verify_bundle", side_effect=result),
            patch.object(c, "verify_measurement"),
            patch.object(c, "wait_memory"),
            patch.object(c.cmp, "one", side_effect=execute) as second,
        ):
            c.run(private, Path("source"), output, "execute")
            self.assertEqual([call.args[1].name for call in second.call_args_list], c.names()[2:])

    def test_invalid_attempt_is_not_accepted_even_with_matching_hashes(self):
        p = self.bundle()
        r = c.read(p / "comparison-result.json")
        r["execution_valid"] = False
        (p / "comparison-result.json").write_text(json.dumps(r))
        (p / "checksums.sha256").write_text(
            "".join(
                hashlib.sha256(x.read_bytes()).hexdigest() + "  " + x.name + "\n"
                for x in p.iterdir()
                if x.name != "checksums.sha256"
            )
        )
        with self.assertRaisesRegex(RuntimeError, "INVALID_ATTEMPT"):
            c.verify_bundle(p)

    def test_documentation_only_is_excluded_from_runtime_identity(self):
        with patch.object(
            c.cmp.env,
            "command",
            side_effect=[
                "scripts/scale_comparison.py\nk8s/README.md",
                "scripts/scale_comparison.py\nk8s/README.md",
                "",
            ],
        ) as command:
            self.assertEqual(c.verify_measurement(), 1)
            self.assertNotIn("k8s/README.md", command.call_args.args[0])
