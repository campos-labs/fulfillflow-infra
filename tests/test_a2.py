"""Recovery policy, uncertain mutation and explicit-request contracts."""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import a1, a2
from scripts.a1_runtime import MARKER, TARGET, WORKLOADS, digest, write_json
from scripts.verify_flow import Failure
from tests.test_a1 import config, snapshot, template

ROOT = Path(__file__).resolve().parents[1]


class Laboratory(a2.ObservedRuntime):
    def __init__(self, root):
        super().__init__(config(), a2.Journal(root))
        self.deployment = {
            "metadata": {"uid": "deployment", "resourceVersion": "1"},
            "spec": {"replicas": 1, "template": template()},
        }
        self.patches = []
        self.reference = "Secret/db/secret-uid/1"
        self.failure = None
        self.diagnostic = "db_pool_size greater than or equal to 1"

    def inventory(self):
        return {
            name: {
                "replicas": 1,
                "uid": name,
                "template_hash": (
                    digest(self.deployment["spec"]["template"]) if name == TARGET else "fixed"
                ),
            }
            for name in WORKLOADS
        }

    def get(self, resource, *args):
        return copy.deepcopy(self.deployment)

    def snapshot(self):
        record = snapshot()
        current = self.deployment["spec"]["template"]
        record["template_hash"] = digest(current)
        record["attempt"] = current["metadata"].get("annotations", {}).get(MARKER)
        record["pods"][0]["attempt"] = record["attempt"]
        faulty = current["spec"]["containers"][0]["env"][0]["value"] == "0"
        if faulty:
            record["status"]["availableReplicas"] = 0
            record["pods"][0]["containers"][0].update(ready=False, exit_code=1)
        return record

    def kubectl(self, *args):
        if args[0] == "get":
            return self.reference + "\n"
        if args[0] == "logs":
            return self.diagnostic
        if args[0] == "patch":
            payload = a2.read(Path(args[-1]))
            assert payload[0]["value"] == self.deployment["metadata"]["uid"]
            assert payload[1]["value"] == self.deployment["metadata"]["resourceVersion"]
            assert payload[2]["value"] == self.deployment["spec"]["template"]
            if self.failure == "before" and self.mutation == "restore":
                raise Failure("SUBPROCESS_TIMEOUT_OUTCOME_UNKNOWN", 5)
            self.deployment["spec"]["template"] = payload[3]["value"]
            self.patches.append(copy.deepcopy(payload[3]["value"]))
            if self.failure == "after" and self.mutation == "restore":
                raise Failure("SUBPROCESS_TIMEOUT_OUTCOME_UNKNOWN", 5)
            return "{}"
        raise AssertionError(args)


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="a2 case ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runtime = Laboratory(self.root)
        self.flows = []
        self.flow_result = {
            "success": True,
            "verdict": "approved",
            "acceptance_verified": True,
            "checkpoint": {"event_id": "unique"},
        }
        mock = patch.object(a2.a1_flow, "verify", side_effect=self.flow)
        mock.start()
        self.addCleanup(mock.stop)
        self.identity("auto")

    def identity(self, condition):
        (self.root / "identity.json").write_text(
            json.dumps(
                {
                    "environment": config().identity(),
                    "condition": condition,
                }
            )
        )

    def flow(self, runtime, destination, secret, *, checkpoint=None):
        self.flows.append(checkpoint)
        destination.mkdir()
        result = copy.deepcopy(self.flow_result)
        write_json(destination / "result.json", result)
        return result

    def invoke(self, scenario="invalid-pool", condition="auto"):
        self.identity(condition)
        return a2.run(self.runtime, self.root, condition, scenario, "do-not-export")

    def prepare(self):
        write_json(self.root / "references.json", {"metadata": a2.references(self.runtime)})
        result = a1.attempt(self.runtime, self.root, "invalid-pool", "secret")
        write_json(self.root / "attempt-result.json", result)
        return result

    def recovery(self):
        output = self.root / ("reconcile-" + str(len(list(self.root.glob("reconcile-*")))))
        output.mkdir()
        return a2.recover(self.runtime, self.root, output, "secret")

    def test_auto_rejects_candidate_then_restores_once_and_checks_business(self):
        result = self.invoke()
        self.assertEqual(result["deployment_verdict"], "rejected")
        self.assertTrue(result["scenario_passed"])
        self.assertEqual(len(self.runtime.patches), 2)
        self.assertEqual(self.runtime.patches[-1], template())
        self.assertEqual(self.flows, [None])
        self.assertEqual(len(self.runtime.journal.phases("restore_send_intent")), 1)

    def test_healthy_never_triggers_restore(self):
        result = self.invoke("healthy")
        self.assertEqual(result["policy_action"], "none")
        self.assertEqual(len(self.runtime.patches), 1)
        self.assertFalse(self.runtime.journal.phases("restore_send_intent"))

    def test_inconclusive_query_never_triggers_restore(self):
        self.flow_result.update(success=False, verdict="inconclusive")
        with self.assertRaises((OSError, Failure)):
            self.invoke("healthy")
        self.assertEqual(len(self.runtime.patches), 1)

    def test_empty_log_then_validation_waits_without_reapplying_candidate(self):
        original = self.runtime.kubectl
        logs = iter(["", "db_pool_size greater than or equal to 1"])
        now = [0.0]
        self.runtime.clock = lambda: now[0]
        self.runtime.sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
        self.runtime.kubectl = lambda *args: next(logs) if args[0] == "logs" else original(*args)
        result = self.invoke()
        self.assertTrue(result["scenario_passed"])
        self.assertEqual(len(self.runtime.patches), 2)
        samples = a2.read(self.root / "diagnostic-observations.json")["samples"]
        self.assertEqual([x["empty"] for x in samples], [True, False])

    def test_permanently_empty_log_is_bounded_and_never_restores(self):
        self.runtime.diagnostic = ""
        now = [0.0]
        self.runtime.clock = lambda: now[0]
        self.runtime.sleep = lambda seconds: now.__setitem__(0, now[0] + seconds)
        with self.assertRaisesRegex(Failure, "EXPECTED_CONFIGURATION_DIAGNOSTIC_MISSING"):
            self.invoke()
        self.assertEqual(now[0], a1.DIAGNOSTIC_SECONDS)
        self.assertEqual(len(self.runtime.patches), 1)
        self.assertFalse(self.runtime.journal.phases("restore_send_intent"))

    def test_log_identity_change_refuses_even_matching_message(self):
        original = self.runtime.snapshot
        calls = [0]

        def changed():
            item = original()
            calls[0] += 1
            if calls[0] >= 4:
                item["pods"][0]["uid"] = "replacement"
            return item

        self.runtime.snapshot = changed
        with self.assertRaisesRegex(Failure, "DIAGNOSTIC_IDENTITY_CHANGED"):
            self.invoke()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_missing_diagnostic_does_not_trigger_policy(self):
        self.runtime.diagnostic = "other failure"
        with self.assertRaisesRegex(Failure, "EXPECTED_CONFIGURATION_DIAGNOSTIC_MISSING"):
            self.invoke()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_scenario_expectation_without_observed_failure_is_ineligible(self):
        self.prepare()
        record = a2.read(self.root / "candidate.json")
        record["pods"][0]["containers"][0]["exit_code"] = None
        (self.root / "candidate.json").write_text(json.dumps(record))
        self.assertFalse(a2.eligible(self.root, config()))

    def test_explicit_condition_waits_for_separate_actor_request(self):
        self.runtime.sleep = lambda seconds: a2.request(self.root, config(), "script")
        result = self.invoke(condition="explicit")
        self.assertFalse(result["automatic_restore"])
        self.assertEqual(result["policy_action"], "explicit_restore")
        self.assertEqual(self.runtime.journal.phases("restoration_requested")[0]["actor"], "script")

    def test_request_for_wrong_condition_or_duplicate_is_rejected(self):
        write_json(self.root / "awaiting-request.json", {"attempt_id": "one"})
        with self.assertRaisesRegex(Failure, "EXPLICIT_CONDITION_REQUIRED"):
            a2.request(self.root, config(), "agent")
        self.identity("explicit")
        a2.request(self.root, config(), "agent")
        with self.assertRaises(FileExistsError):
            a2.request(self.root, config(), "agent")

    def test_write_failure_before_restore_intent_prevents_patch(self):
        self.prepare()
        original = a2.write_json

        def fail(path, value):
            if value.get("phase") == "restore_send_intent":
                raise OSError("disk full")
            original(path, value)

        with patch.object(a2, "write_json", side_effect=fail), self.assertRaises(OSError):
            self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_lost_restore_response_reconciles_healthy_without_second_patch(self):
        self.prepare()
        self.runtime.failure = "after"
        with self.assertRaisesRegex(Failure, "OUTCOME_UNKNOWN"):
            self.recovery()
        self.runtime.journal = a2.Journal(self.root)
        self.assertTrue(self.recovery()["scenario_passed"])
        self.assertEqual(len(self.runtime.patches), 2)

    def test_uncertain_request_still_showing_candidate_is_not_repeated(self):
        self.prepare()
        self.runtime.failure = "before"
        with self.assertRaises(Failure):
            self.recovery()
        with self.assertRaisesRegex(Failure, "RESTORE_OUTCOME_UNRESOLVED_NO_RETRY"):
            self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_repeat_recovery_only_reads_previously_accepted_event(self):
        self.invoke()
        self.assertTrue(self.recovery()["scenario_passed"])
        self.assertEqual(self.flows, [None, {"event_id": "unique"}])
        self.assertEqual(len(self.runtime.patches), 2)

    def test_interrupted_http_observation_never_offers_replacement(self):
        self.invoke()
        folder = self.root / self.runtime.journal.phases("recovery_flow_started")[0]["directory"]
        (folder / "result.json").unlink()
        with self.assertRaisesRegex(Failure, "RECOVERY_FLOW_INCOMPLETE_NO_REOFFER"):
            self.recovery()
        self.assertEqual(len(self.flows), 1)

    def test_changed_external_secret_metadata_prevents_restoration(self):
        self.prepare()
        self.runtime.reference += "changed"
        with self.assertRaisesRegex(Failure, "REFERENCE_CHANGED"):
            self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_changed_deployment_uid_template_replicas_or_environment_refused(self):
        self.prepare()
        original = copy.deepcopy(self.runtime.deployment)
        for kind in ("uid", "template", "replicas"):
            with self.subTest(kind=kind):
                self.runtime.deployment = copy.deepcopy(original)
                if kind == "uid":
                    self.runtime.deployment["metadata"]["uid"] = "new"
                if kind == "template":
                    self.runtime.deployment["spec"]["template"]["metadata"]["extra"] = "x"
                if kind == "replicas":
                    self.runtime.deployment["spec"]["replicas"] = 2
                with self.assertRaises(Failure):
                    self.recovery()
        self.runtime.deployment = original
        self.runtime.config = config()
        data = a2.read(self.root / "identity.json")
        data["environment"]["namespace_uid"] = "another"
        (self.root / "identity.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(Failure, "RESTORE_ENVIRONMENT_MISMATCH"):
            self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_recovery_business_failure_never_claims_success(self):
        self.flow_result.update(success=False, verdict="inconclusive")
        result = self.invoke()
        self.assertFalse(result["scenario_passed"])
        self.assertFalse(result["recovery"]["recovery_passed"])

    def test_partial_or_changed_journal_refused_and_secrets_not_exported(self):
        self.invoke()
        text = "".join(p.read_text() for p in self.root.rglob("*.json"))
        self.assertNotIn("do-not-export", text)
        path = self.root / "journal/0000.json"
        value = a2.read(path)
        value["phase"] = "changed"
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(Failure, "JOURNAL_CHAIN_INVALID"):
            a2.Journal(self.root)
        path.write_text("{")
        with self.assertRaises(ValueError):
            a2.Journal(self.root)

    def test_third_party_restoring_template_does_not_count_as_policy_success(self):
        self.prepare()
        self.runtime.deployment["spec"]["template"] = template()
        with self.assertRaisesRegex(Failure, "UNEXPECTED_HEALTHY_TEMPLATE"):
            self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)
        self.assertEqual(self.flows, [])

    def test_explicit_deadline_does_not_restore_without_request(self):
        self.runtime.sleep = lambda seconds: setattr(self.runtime, "deadline", 0)
        with self.assertRaisesRegex(Failure, "OPERATION_DEADLINE"):
            self.invoke(condition="explicit")
        self.assertEqual(len(self.runtime.patches), 1)
        self.assertFalse(self.runtime.journal.phases("restore_send_intent"))

    def test_restore_rollout_failure_stops_without_second_mutation(self):
        self.prepare()
        with patch.object(self.runtime, "wait_target", side_effect=Failure("ROLLOUT_DEADLINE", 5)):
            with self.assertRaisesRegex(Failure, "ROLLOUT_DEADLINE"):
                self.recovery()
        self.assertEqual(len(self.runtime.patches), 2)
        self.assertEqual(self.flows, [])

    def test_other_workload_change_is_not_repaired(self):
        self.prepare()
        inventory = self.runtime.inventory()
        inventory["core"]["template_hash"] = "changed"
        with patch.object(self.runtime, "inventory", return_value=inventory):
            with self.assertRaisesRegex(Failure, "OTHER_WORKLOAD_CHANGED"):
                self.recovery()
        self.assertEqual(len(self.runtime.patches), 1)

    def test_mismatched_request_does_not_restore(self):
        def invalid_request(seconds):
            write_json(
                self.root / "restore-request.json", {"attempt_id": "wrong", "actor": "agent"}
            )

        self.runtime.sleep = invalid_request
        with self.assertRaisesRegex(Failure, "REQUEST_ATTEMPT_MISMATCH"):
            self.invoke(condition="explicit")
        self.assertEqual(len(self.runtime.patches), 1)

    def test_evidence_failure_before_candidate_send_leaves_cluster_untouched(self):
        with patch.object(self.runtime.journal, "emit", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.invoke()
        self.assertEqual(self.runtime.patches, [])
        self.assertTrue(self.recovery()["scenario_passed"])
        self.assertEqual(self.runtime.patches, [])

    def test_concurrent_cli_refused_before_cluster_access(self):
        import contextlib
        import io

        from scripts.a1_runtime import environment_lock

        cfg = self.root / "config.json"
        write_json(cfg, config().__dict__)
        with (
            environment_lock(config()),
            patch.dict(os.environ, {"CARRIER_ALPHA_WEBHOOK_SECRET": "secret"}),
        ):
            with (
                patch.object(a2, "ObservedRuntime") as runtime,
                contextlib.redirect_stderr(io.StringIO()),
            ):
                code = a2.main(
                    [
                        "--config",
                        str(cfg),
                        "--output",
                        str(self.root / "busy"),
                        "--mode",
                        "run",
                        "--condition",
                        "auto",
                        "--scenario",
                        "healthy",
                    ]
                )
        self.assertEqual(code, 2)
        runtime.assert_not_called()
        self.assertEqual(a2.read(self.root / "busy/result.json")["error"], "ENVIRONMENT_BUSY")

    def test_launcher_real_powershell_forwards_space_paths_and_exit_status(self):
        pwsh = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
        self.assertIsNotNone(pwsh)
        shutil.copyfile(ROOT / "scripts/Invoke-A2.ps1", self.root / "Invoke-A2.ps1")
        (self.root / "a2.py").write_text(
            "import sys,json; print(json.dumps(sys.argv[1:])); sys.exit(7)"
        )
        result = subprocess.run(
            [
                pwsh,
                "-NoProfile",
                "-File",
                str(self.root / "Invoke-A2.ps1"),
                "-Python",
                sys.executable,
                "-Config",
                str(self.root / "config file.json"),
                "-OutputDirectory",
                str(self.root / "new output"),
                "-Mode",
                "request",
                "-Source",
                str(self.root / "old output"),
                "-Actor",
                "agent",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 7, result.stderr)
        self.assertIn(str(self.root / "old output"), json.loads(result.stdout))


if __name__ == "__main__":
    unittest.main()
