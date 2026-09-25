"""Safety and measurement contracts for the separate A complements."""

from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from scripts import a1_flow, a2
from scripts import a_complements as complements
from scripts import verify_flow as flow
from scripts.a1_runtime import write_json
from tests.test_a1 import config
from tests.test_a2 import Laboratory
from tests.test_verify_flow import EVENT, SECRET, PublicApi


class ComplementsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="A complement ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_order_and_units_remain_separate(self):
        pilot, evaluation = complements.order(True), complements.order(False)
        self.assertEqual(len(pilot), 3)
        self.assertEqual(len(evaluation), 9)
        self.assertEqual(
            [c["condition"] for c in evaluation[:6]],
            ["explicit", "auto", "auto", "explicit", "explicit", "auto"],
        )
        self.assertTrue(all(c["scenario"] == "inconclusive" for c in evaluation[6:]))

    def pending(self):
        return {
            "tracking_event_id": EVENT,
            "required": True,
            "publication": "SENT",
            "processing": "NOT_RECEIVED",
            "status": None,
            "notification_id": None,
        }

    def test_pending_is_published_not_consumed(self):
        self.assertTrue(complements.pending_record(self.pending(), EVENT))
        queued = self.pending()
        queued["publication"] = "PENDING"
        self.assertFalse(complements.pending_record(queued, EVENT))

    def test_received_completed_blocked_wrong_event_reject_preparation(self):
        for change in (
            {"processing": "PENDING"},
            {"processing": "DONE"},
            {"publication": "BLOCKED"},
            {"tracking_event_id": "wrong"},
            {"notification_id": "unexpected"},
        ):
            with self.subTest(change=change), self.assertRaises(flow.Failure):
                complements.pending_record({**self.pending(), **change}, EVENT)

    def test_observation_failure_preserves_acceptance_and_resume_is_get_only(self):
        api = PublicApi()
        runtime = type("Runtime", (), {"config": config(), "remaining": lambda self: 90})()
        fault = complements.QueryFault(api)
        result = a1_flow.verify(
            runtime,
            self.root / "fault",
            SECRET,
            transport=fault,
            base="http://127.0.0.1:8000",
        )
        self.assertEqual(fault.injected, 1)
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertTrue(result["acceptance_verified"])
        request_count = len(api.requests)
        resumed = a1_flow.verify(
            runtime,
            self.root / "resume",
            SECRET,
            checkpoint=result["checkpoint"],
            transport=api,
            base="http://127.0.0.1:8000",
        )
        self.assertTrue(resumed["success"])
        self.assertTrue(all(r[0] == "GET" for r in api.requests[request_count:]))
        self.assertEqual(len(api.webhooks), 1)

    def test_injection_is_scoped_and_does_not_retry(self):
        fault = complements.QueryFault(lambda *a: flow.Response(200, {}, b"{}"))
        self.assertEqual(fault("GET", "http://127.0.0.1/health", {}, None, 1).status, 200)
        self.assertEqual(
            fault("GET", "http://127.0.0.1/api/v1/notification-status/x", {}, None, 1).status, 503
        )
        with self.assertRaisesRegex(flow.Failure, "UNEXPECTED_RETRY"):
            fault("GET", "http://127.0.0.1/api/v1/notification-status/x", {}, None, 1)

    def test_policy_does_not_restore_if_preparation_fails(self):
        runtime = Laboratory(self.root)

        def fail(*args):
            raise flow.Failure("NO_CONFIRMED_PENDING_WORK")

        with self.assertRaisesRegex(flow.Failure, "NO_CONFIRMED_PENDING_WORK"):
            a2.run(runtime, self.root, "auto", "invalid-pool", SECRET, prepare_recovery=fail)
        self.assertEqual(len(runtime.patches), 1)
        self.assertFalse(runtime.journal.phases("restore_send_intent"))
        self.assertFalse(runtime.journal.phases("policy_authorized"))

    def test_configuration_drift_during_preparation_blocks_policy(self):
        runtime = Laboratory(self.root)
        write_json(self.root / "identity.json", {"environment": runtime.config.identity()})

        def drift(*args):
            runtime.reference = "new-secret-reference"

        with self.assertRaisesRegex(flow.Failure, "REFERENCE_CHANGED"):
            a2.run(runtime, self.root, "auto", "invalid-pool", SECRET, prepare_recovery=drift)
        self.assertEqual(len(runtime.patches), 1)
        self.assertFalse(runtime.journal.phases("policy_authorized"))

    def test_abstention_checks_configuration_and_actual_journal(self):
        runtime = Laboratory(self.root)
        runtime.deployment["metadata"]["generation"] = 1
        before = complements.mutation_identity(runtime)
        self.assertEqual(complements.assert_abstained(runtime, before)["restore_sent"], 0)
        runtime.deployment["metadata"]["generation"] = 2
        with self.assertRaisesRegex(flow.Failure, "CONFIGURATION_CHANGED"):
            complements.assert_abstained(runtime, before)
        runtime.deployment["metadata"]["generation"] = 1
        runtime.journal.emit("restore_send_intent")
        with self.assertRaisesRegex(flow.Failure, "UNEXPECTED_RESTORE"):
            complements.assert_abstained(runtime, before)

    def test_timed_observer_refuses_any_mutation(self):
        observer = complements.TimedReads(0, EVENT)
        with self.assertRaisesRegex(flow.Failure, "READ_ONLY"):
            observer("POST", "http://127.0.0.1/events", {}, b"{}", 1)

    def test_preparation_persists_checkpoint_without_duplicate_or_reoffer(self):
        api = PublicApi(notifications=["NOT_RECEIVED"])

        @contextmanager
        def tunnel(runtime):
            yield "http://127.0.0.1:8000", {"uid": "core"}

        runtime = type("Runtime", (), {"config": config()})()
        with (
            patch.object(a1_flow, "tunnel", tunnel),
            patch.object(flow, "HttpTransport", return_value=api),
        ):
            result = complements.prepare_pending(runtime, self.root, SECRET)
        self.assertEqual(result["pending_stage"], "published_not_received")
        self.assertEqual(len(api.webhooks), 1)
        self.assertTrue(result["tracking_completed"] and result["order_completed"])
        self.assertFalse(result["notifications_simulated"])

    def test_preparation_failure_keeps_accepted_identity_and_does_not_retry(self):
        api = PublicApi()

        @contextmanager
        def tunnel(runtime):
            yield "http://127.0.0.1:8000", {"uid": "core"}

        runtime = type("Runtime", (), {"config": config()})()
        with (
            patch.object(a1_flow, "tunnel", tunnel),
            patch.object(flow, "HttpTransport", return_value=api),
        ):
            with self.assertRaises(flow.Failure):
                complements.prepare_pending(runtime, self.root, SECRET)
        result = a2.read(self.root / "flow/result.json")
        self.assertTrue(result["acceptance_verified"])
        self.assertEqual(result["verdict"], "inconclusive")
        self.assertEqual(len(api.webhooks), 1)

    def test_inconclusive_hook_exercises_existing_policy_without_restore(self):
        runtime = Laboratory(self.root)

        def inconclusive(*args):
            return {"verdict": "inconclusive", "success": False, "acceptance_verified": True}

        with self.assertRaisesRegex(flow.Failure, "NO_DEFINITIVE_STARTUP_FAILURE"):
            a2.run(runtime, self.root, "auto", "healthy", SECRET, flow_verifier=inconclusive)
        self.assertEqual(len(runtime.patches), 1)
        self.assertFalse(runtime.journal.phases("restore_send_intent"))

    def test_parallel_observers_begin_before_gate_and_preserve_get_only_recovery(self):
        import threading
        import time

        from tests.test_a1 import snapshot

        gate = threading.Event()
        api = PublicApi(notifications=["NOT_RECEIVED"])

        @contextmanager
        def tunnel(runtime):
            yield "http://127.0.0.1:8000", {"uid": "core"}

        cfg = config(poll_seconds=0.1)
        runtime = type("Runtime", (), {"config": cfg, "remaining": lambda self: 90})()
        with (
            patch.object(a1_flow, "tunnel", tunnel),
            patch.object(flow, "HttpTransport", return_value=api),
        ):
            prepared = complements.prepare_pending(runtime, self.root, SECRET)
        initial_count = len(api.requests)

        def sample():
            result = snapshot()
            result["template_hash"] = "healthy" if gate.is_set() else "faulty"
            if not gate.is_set():
                result["status"]["availableReplicas"] = 0
            return result

        runtime.snapshot = sample

        def transport(*args):
            api.notification_states = ["DONE" if gate.is_set() else "NOT_RECEIVED"]
            return api(*args)

        with (
            patch.object(a1_flow, "tunnel", tunnel),
            patch.object(flow, "HttpTransport", return_value=transport),
            patch.object(complements, "Runtime", return_value=runtime),
        ):
            observer = complements.ParallelSignals(
                cfg,
                self.root,
                prepared["checkpoint"],
                SECRET,
                time.monotonic(),
                "healthy",
                sample()["deployment_uid"],
            )
            try:
                observer.start()
                self.assertIsNone(observer.converged_at)
                self.assertIsNone(observer.transport.simulated_at)
            finally:
                gate.set()
            result = observer.finish()
        self.assertTrue(result["functional"]["success"])
        self.assertIsNotNone(result["difference_seconds"])
        self.assertTrue(all(r[0] == "GET" for r in api.requests[initial_count:]))
        self.assertEqual(len(api.webhooks), 1)

    def test_evaluation_requires_intact_successful_pilot_with_same_scripts(self):
        from scripts import a2_campaign

        provenance = {"script_hashes": {"x": "frozen"}, "application_sha": "application"}
        write_json(
            self.root / "protocol.json",
            {
                "stage": "pilot",
                "order": complements.order(True),
                "environment": config().identity(),
                "provenance": provenance,
            },
        )
        a2_campaign.export(
            self.root,
            {
                "complete": True,
                "attempts": [
                    {**case, "usable": True, "scenario_passed": True}
                    for case in complements.order(True)
                ],
            },
        )
        self.addCleanup(self.root.with_suffix(".zip").unlink)
        complements.validate_pilot(self.root, config(), provenance)
        with self.assertRaisesRegex(flow.Failure, "IMPLEMENTATION_CHANGED"):
            complements.validate_pilot(
                self.root,
                config(),
                {
                    **provenance,
                    "script_hashes": {"x": "changed"},
                },
            )
        (self.root / "summary.json").write_text("{}")
        with self.assertRaisesRegex(flow.Failure, "HASH_MISMATCH"):
            complements.validate_pilot(self.root, config(), provenance)

    def test_powershell_launcher_preserves_spaces_stage_and_exit_code(self):
        import json
        import os
        import shutil
        import subprocess
        import sys

        pwsh = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
        self.assertTrue(pwsh, "PowerShell is required for this operational interface")
        source = Path(__file__).resolve().parents[1] / "scripts/Invoke-AComplements.ps1"
        shutil.copy(source, self.root / source.name)
        (self.root / "a_complements.py").write_text(
            "import sys,json; print(json.dumps(sys.argv[1:])); sys.exit(7)"
        )
        cfg = self.root / "config file.json"
        cfg.write_text("{}")
        settings = self.root / "settings local.json"
        settings.write_text(
            json.dumps(
                {
                    "python": sys.executable,
                    "config": str(cfg),
                    "output": str(self.root / "new run"),
                    "expected_sha": "test",
                    "pilot_source": str(self.root / "pilot data"),
                }
            )
        )
        response = subprocess.run(
            [
                str(pwsh),
                "-NoProfile",
                "-File",
                str(self.root / source.name),
                "-SettingsFile",
                str(settings),
                "-Mode",
                "Check",
                "-Stage",
                "evaluation",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(response.returncode, 7, response.stderr)
        args = json.loads(response.stdout)
        self.assertIn("--check-only", args)
        self.assertEqual(args[args.index("--stage") + 1], "evaluation")
        self.assertEqual(args[args.index("--pilot-source") + 1], str(self.root / "pilot data"))

    def test_sequence_stops_without_replacement_and_pauses_on_unexpected_failure(self):
        from contextlib import ExitStack
        from unittest.mock import Mock

        from scripts import a1, a2_campaign

        for failure in (False, True):
            with self.subTest(failure=failure), ExitStack() as stack:
                folder = self.root / str(failure)
                folder.mkdir()
                for name in ("host_check", "prepare_runtime", "cleanup"):
                    stack.enter_context(patch.object(a2_campaign, name))
                stack.enter_context(
                    patch.object(a2_campaign, "health", return_value={"base": "fixed"})
                )
                stack.enter_context(patch.object(a2_campaign, "power_identity", return_value={}))
                stack.enter_context(patch.object(a1, "provenance", return_value={}))
                pause = stack.enter_context(
                    patch.object(a1, "lifecycle", return_value={"scenario_passed": True})
                )
                stack.enter_context(patch.object(complements, "Runtime", return_value=Mock()))

                def fake_attempt(*args):
                    args[2].mkdir()
                    if failure:
                        raise flow.Failure("UNEXPECTED")
                    return {"scenario_passed": True, "scenario": "invalid-pool"}

                attempt = stack.enter_context(
                    patch.object(
                        complements,
                        "one_attempt",
                        side_effect=fake_attempt,
                    )
                )
                result = complements.execute(
                    config(), self.root / "config", folder, {}, SECRET, True
                )
                self.assertEqual(result["complete"], not failure)
                self.assertEqual(len(result["attempts"]), 1 if failure else 3)
                self.assertEqual(attempt.call_count, 1 if failure else 3)
                self.assertEqual(
                    [row["scenario"] for row in result["attempts"]],
                    [
                        case["scenario"]
                        for case in complements.order(True)[: len(result["attempts"])]
                    ],
                )
                self.assertTrue(result["shutdown"]["scenario_passed"])
                pause.assert_called_once()


if __name__ == "__main__":
    unittest.main()
