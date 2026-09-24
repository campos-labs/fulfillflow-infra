"""Safety/identity contracts and functional observations; cluster pilot remains separate."""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import a1, a1_flow
from scripts.a1_runtime import (
    MARKER,
    Config,
    Runtime,
    candidate_crashed,
    converged,
    environment_lock,
    owned_by,
    pod_record,
    validate_template,
    write_json,
)
from scripts.verify_flow import Failure
from tests.test_verify_flow import SECRET, PublicApi

ROOT = Path(__file__).resolve().parents[1]
UID = "c39f1d8c-0928-4da9-9b8e-f8090113aec1"


def config(**kwargs):
    return Config(
        kubectl=sys.executable,
        docker=sys.executable,
        kubeconfig=sys.executable,
        context="kind-fixture",
        namespace="fulfillflow",
        namespace_uid=UID,
        node="fixture-control-plane",
        image="fulfillflow-kind-runtime:source-9e3a135a00db",
        image_id="sha256:" + "a" * 64,
        **kwargs,
    )


def template():
    return {
        "metadata": {"annotations": {}},
        "spec": {
            "containers": [
                {
                    "image": config().image,
                    "env": [
                        {"name": "DB_POOL_SIZE", "value": "3"},
                        {
                            "name": "DATABASE_URL",
                            "valueFrom": {"secretKeyRef": {"name": "db", "key": "DATABASE_URL"}},
                        },
                    ],
                }
            ]
        },
    }


def snapshot():
    return {
        "deployment_uid": "deployment",
        "template_hash": "hash",
        "generation": 3,
        "attempt": "new",
        "desired": 1,
        "status": {
            "observedGeneration": 3,
            "updatedReplicas": 1,
            "availableReplicas": 1,
            "replicas": 1,
        },
        "pods": [
            {
                "uid": "pod",
                "name": "candidate",
                "attempt": "new",
                "deleting": False,
                "containers": [
                    {"image_id": config().image_id, "ready": True, "exit_code": None, "restarts": 0}
                ],
            }
        ],
    }


class SafetyTests(unittest.TestCase):
    def test_old_pod_extra_replica_wrong_image_and_unobserved_generation_never_pass(self):
        record = snapshot()
        self.assertTrue(converged(record, config()))
        for change in ("old", "extra", "image", "generation", "deleting"):
            candidate = copy.deepcopy(record)
            if change == "old":
                candidate["pods"][0]["attempt"] = "old"
            if change == "extra":
                candidate["pods"].append(copy.deepcopy(candidate["pods"][0]))
            if change == "image":
                candidate["pods"][0]["containers"][0]["image_id"] = "wrong"
            if change == "generation":
                candidate["status"]["observedGeneration"] = 2
            if change == "deleting":
                candidate["pods"][0]["deleting"] = True
            with self.subTest(change=change):
                self.assertFalse(converged(candidate, config()))

    def test_crashed_old_revision_is_not_the_injected_failure(self):
        record = snapshot()
        record["pods"][0]["containers"][0].update(ready=False, exit_code=1)
        self.assertTrue(candidate_crashed(record, config()))
        record["pods"][0]["attempt"] = "old"
        self.assertFalse(candidate_crashed(record, config()))

    def test_revision_changes_only_annotation_and_selected_nonsensitive_setting(self):
        healthy = template()
        candidate = a1.revision(healthy, "attempt", "invalid-pool")
        self.assertEqual(healthy["spec"]["containers"][0]["env"][0]["value"], "3")
        candidate["metadata"]["annotations"].pop(MARKER)
        candidate["spec"]["containers"][0]["env"][0]["value"] = "3"
        self.assertEqual(candidate, healthy)

    def test_inline_secret_never_enters_snapshot_or_restore_manifest(self):
        value = template()
        validate_template(value, config())
        value["spec"]["containers"][0]["env"][1] = {"name": "DATABASE_URL", "value": SECRET}
        with self.assertRaisesRegex(Failure, "INLINE_SECRET_FORBIDDEN"):
            validate_template(value, config())

    def test_environment_lock_is_exclusive_and_released_after_failure(self):
        with self.assertRaisesRegex(RuntimeError, "injected"):
            with environment_lock(config()):
                with self.assertRaisesRegex(Failure, "ENVIRONMENT_BUSY"):
                    with environment_lock(config()):
                        pass
                raise RuntimeError("injected")
        with environment_lock(config()):
            pass

    def test_config_rejects_cloud_context_invalid_path_and_unbounded_time(self):
        for changes in (
            {"context": "aks-example"},
            {"kubectl": "relative"},
            {"operation_seconds": float("inf")},
            {"flow_seconds": 0},
        ):
            bad = {**config().__dict__, **changes}
            with self.subTest(changes=changes), self.assertRaises(Failure):
                Config(**bad).validate()

    def test_subprocess_exit_and_timeout_are_not_retried_or_leaked(self):
        runtime = Runtime(config())
        for result in (
            subprocess.CompletedProcess([], 7, "", SECRET),
            subprocess.TimeoutExpired("command", 1, stderr=SECRET),
        ):
            with patch("scripts.a1_runtime.subprocess.run") as run:
                if isinstance(result, Exception):
                    run.side_effect = result
                else:
                    run.return_value = result
                with self.assertRaises(Failure) as caught:
                    runtime.command([sys.executable, "-V"])
                self.assertNotIn(SECRET, str(caught.exception))
                run.assert_called_once()

    def test_patch_is_compare_and_swap_and_never_retries_mutation(self):
        runtime = Runtime(config())
        runtime.kubectl = Mock(side_effect=Failure("CONFLICT"))
        deployment = {
            "metadata": {"uid": "u", "resourceVersion": "9"},
            "spec": {"template": template()},
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "patch.json"
            with self.assertRaises(Failure):
                runtime.patch_template(deployment, template(), output)
            patch_record = json.loads(output.read_text())
            self.assertEqual([x["op"] for x in patch_record], ["test", "test", "test", "replace"])
            self.assertEqual(patch_record[1]["value"], "9")
            runtime.kubectl.assert_called_once()

    def test_evidence_cannot_overwrite_and_failed_restore_does_not_mutate(self):
        runtime = Runtime(config())
        runtime.get = Mock(return_value={"metadata": {"uid": "changed"}})
        runtime.patch_template = Mock()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            write_json(
                source / "restore.json", {"identity": config().identity(), "deployment_uid": "old"}
            )
            with self.assertRaises(FileExistsError):
                write_json(source / "restore.json", {})
            with self.assertRaisesRegex(Failure, "RESTORE_DEPLOYMENT_CHANGED"):
                a1.restore(runtime, source, source, SECRET)
            runtime.patch_template.assert_not_called()

    def test_wrong_namespace_stops_preflight_before_mutation(self):
        runtime = Runtime(config())
        runtime.kubectl = Mock(
            return_value=json.dumps(
                {"clusters": [{"cluster": {"server": "https://127.0.0.1:12345"}}]}
            )
        )
        runtime.get = Mock(return_value={"metadata": {"uid": "different"}})
        with self.assertRaisesRegex(Failure, "NAMESPACE_IDENTITY_MISMATCH"):
            runtime.preflight()
        runtime.get.assert_called_once()

    def test_record_omits_container_message_and_checks_controller_ownership(self):
        pod = {
            "metadata": {
                "name": "p",
                "uid": "u",
                "ownerReferences": [{"uid": "r", "controller": True}],
            },
            "status": {
                "containerStatuses": [
                    {
                        "name": "c",
                        "image": "i",
                        "state": {"terminated": {"exitCode": 1, "message": SECRET}},
                    }
                ]
            },
        }
        self.assertNotIn(SECRET, json.dumps(pod_record(pod)))
        self.assertTrue(owned_by(pod, "r"))
        self.assertFalse(owned_by(pod, "other"))

    def test_other_workload_or_candidate_restart_invalidates_attribution(self):
        with self.assertRaisesRegex(Failure, "OTHER_WORKLOAD_CHANGED"):
            a1.other_workloads_unchanged({"core": 1}, {"core": 2})
        before, after = snapshot(), snapshot()
        after["pods"][0]["containers"][0]["restarts"] = 1
        with self.assertRaisesRegex(Failure, "CANDIDATE_EXECUTION_CHANGED"):
            a1.stable_pod(before, after)


class ObservationTests(unittest.TestCase):
    def test_healthy_records_original_queries_and_resume_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            api = PublicApi()
            result = a1_flow.verify(
                Runtime(config()),
                Path(directory) / "new",
                SECRET,
                transport=api,
                base="http://localhost",
            )
            self.assertEqual(result["verdict"], "approved")
            self.assertTrue(result["duplicate_verified"])
            api.requests.clear()
            recovered = a1_flow.verify(
                Runtime(config()),
                Path(directory) / "old",
                SECRET,
                checkpoint=result["checkpoint"],
                transport=api,
                base="http://localhost",
            )
            self.assertEqual(recovered["verdict"], "approved")
            self.assertTrue(all(r[0] == "GET" for r in api.requests))
            text = (Path(directory) / "new/observations.jsonl").read_text()
            self.assertIn('"public_query"', text)
            self.assertIn('"SIMULATED"', text)
            self.assertNotIn(SECRET, text)
            self.assertNotIn("Recipient", text)

    def test_query_failure_is_inconclusive_with_acceptance_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            api = PublicApi()
            api.query_status = 503
            result = a1_flow.verify(
                Runtime(config()),
                Path(directory) / "new",
                SECRET,
                transport=api,
                base="http://localhost",
            )
            self.assertEqual(result["verdict"], "inconclusive")
            self.assertTrue(result["acceptance_verified"])
            self.assertEqual(len(api.webhooks), 1)
            self.assertIn("inbox_event_id", result["checkpoint"])

    def test_lost_admission_stays_unknown_without_retry(self):
        api = PublicApi()

        def transport(method, url, headers, body, timeout):
            if "/carriers/" in url:
                raise Failure("HTTP_TIMEOUT_OUTCOME_UNKNOWN", 3)
            return api(method, url, headers, body, timeout)

        with tempfile.TemporaryDirectory() as directory:
            result = a1_flow.verify(
                Runtime(config()),
                Path(directory) / "new",
                SECRET,
                transport=transport,
                base="http://localhost",
            )
            self.assertEqual(result["verdict"], "inconclusive")
            self.assertTrue(result["webhook_offered"])
            self.assertFalse(result["acceptance_verified"])

    def test_launcher_forwards_paths_with_spaces_and_child_failure_in_real_powershell(self):
        pwsh = os.environ.get("PWSH_PATH") or shutil.which("pwsh")
        self.assertIsNotNone(pwsh, "PowerShell required for this cross-platform gate")
        with tempfile.TemporaryDirectory(prefix="a1 paths ") as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / "scripts/Invoke-A1.ps1", root / "Invoke-A1.ps1")
            (root / "a1.py").write_text(
                "import sys,json; print(json.dumps(sys.argv[1:])); sys.exit(7)"
            )
            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-File",
                    str(root / "Invoke-A1.ps1"),
                    "-Python",
                    sys.executable,
                    "-Config",
                    str(root / "config file.json"),
                    "-OutputDirectory",
                    str(root / "new output"),
                    "-Mode",
                    "restore",
                    "-Source",
                    str(root / "old output"),
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(result.returncode, 7, result.stderr)
            self.assertIn(str(root / "old output"), json.loads(result.stdout))

    def test_existing_output_rejected_without_cluster_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            write_json(path / "config.json", config().__dict__)
            with patch.object(a1, "Runtime") as runtime, contextlib.redirect_stderr(io.StringIO()):
                code = a1.main(
                    [
                        "--mode",
                        "status",
                        "--config",
                        str(path / "config.json"),
                        "--output",
                        str(path),
                    ]
                )
            self.assertEqual(code, 2)
            runtime.assert_not_called()


class AttemptTests(unittest.TestCase):
    def runtime(self):
        runtime = Mock(spec=Runtime)
        runtime.config = config()
        runtime.inventory.return_value = {
            "core": {"replicas": 1},
            "notifications-worker": {"replicas": 1},
        }
        runtime.get.return_value = {
            "metadata": {"uid": "deployment", "resourceVersion": "1"},
            "spec": {"template": template()},
        }
        runtime.snapshot.return_value = snapshot()

        def wait(candidate_hash, **kwargs):
            record = snapshot()
            record["template_hash"] = candidate_hash
            record["pods"][0]["attempt"] = runtime.patch_template.call_args.args[1]["metadata"][
                "annotations"
            ][MARKER]
            record["attempt"] = record["pods"][0]["attempt"]
            record["pods"][0]["containers"][0].update(ready=False, exit_code=1)
            return record

        runtime.wait_target.side_effect = wait
        return runtime

    def test_expected_fault_passes_scenario_but_rejects_deployment_without_auto_restore(self):
        runtime = self.runtime()
        runtime.kubectl.return_value = "db_pool_size: Input should be greater than or equal to 1"
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(a1_flow, "verify") as verifier,
        ):
            result = a1.attempt(runtime, Path(directory), "invalid-pool", SECRET)
            self.assertTrue(result["scenario_passed"])
            self.assertEqual(result["deployment_verdict"], "rejected")
            self.assertEqual(result["accepted_events"], 0)
            self.assertEqual(runtime.patch_template.call_count, 1)
            verifier.assert_not_called()
            healthy = json.loads((Path(directory) / "restore.json").read_text())["healthy_template"]
            self.assertEqual(healthy, template())

    def test_unrelated_crash_is_not_accepted_as_expected_fault(self):
        runtime = self.runtime()
        runtime.kubectl.return_value = "different failure"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Failure, "EXPECTED_CONFIGURATION_DIAGNOSTIC_MISSING"):
                a1.attempt(runtime, Path(directory), "invalid-pool", SECRET)
            self.assertEqual(runtime.patch_template.call_count, 1)

    def test_rollout_deadline_is_finite_without_reapplying(self):
        elapsed = [0]
        runtime = Runtime(
            config(rollout_seconds=5),
            clock=lambda: elapsed[0],
            sleep=lambda value: elapsed.__setitem__(0, elapsed[0] + value),
        )
        record = snapshot()
        record["status"]["availableReplicas"] = 0
        runtime.snapshot = Mock(return_value=record)
        with self.assertRaisesRegex(Failure, "ROLLOUT_DEADLINE"):
            runtime.wait_target("hash")
        self.assertEqual(elapsed[0], 5)

    def test_incomplete_previous_flow_is_not_reported_recovered_by_fresh_success(self):
        runtime = self.runtime()
        runtime.wait_target.side_effect = None
        runtime.wait_target.return_value = snapshot()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / "source", root / "restoration"
            source.mkdir()
            output.mkdir()
            (source / "flow").mkdir()
            candidate = a1.revision(template(), "a", "healthy")
            runtime.get.return_value["spec"]["template"] = candidate
            write_json(
                source / "restore.json",
                {
                    "identity": config().identity(),
                    "deployment_uid": "deployment",
                    "healthy_template": template(),
                    "candidate_template": candidate,
                    "scenario": "healthy",
                    "inventory": runtime.inventory(),
                    "attempt_id": "a",
                },
            )
            with patch.object(
                a1_flow, "verify", return_value={"success": True, "verdict": "approved"}
            ):
                result = a1.restore(runtime, output, source, SECRET)
            self.assertTrue(result["restored_configuration"])
            self.assertFalse(result["scenario_passed"])
            self.assertEqual(result["previous_event"]["state"], "flow_record_incomplete")

    def test_evidence_write_failure_cannot_emit_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root / "config.json", config().__dict__)
            error = io.StringIO()
            with (
                patch.object(a1, "provenance", return_value={}),
                patch.object(a1, "write_json", side_effect=OSError(SECRET)),
                contextlib.redirect_stderr(error),
            ):
                code = a1.main(
                    [
                        "--mode",
                        "status",
                        "--config",
                        str(root / "config.json"),
                        "--output",
                        str(root / "new"),
                    ]
                )
            self.assertEqual(code, 2)
            self.assertNotIn(SECRET, error.getvalue())
            self.assertTrue(json.loads(error.getvalue())["evidence_write_failed"])


class LifecycleTests(unittest.TestCase):
    def runtime(self, replicas):
        runtime = Mock(spec=Runtime)
        runtime.config = config()
        runtime.deadline = 600
        runtime.clock = Mock(return_value=0)
        runtime.prefix.return_value = ["kubectl"]
        runtime.inventory.return_value = {}

        def get(resource):
            if resource == "statefulsets":
                return {
                    "items": [
                        {
                            "metadata": {
                                "name": name,
                                "labels": {"app.kubernetes.io/part-of": "fulfillflow"},
                            }
                        }
                        for name in ("postgres", "rabbitmq")
                    ]
                }
            if resource == "jobs":
                return {
                    "items": [
                        {"metadata": {"name": "migrate-" + owner}, "status": {"succeeded": 1}}
                        for owner in ("core", "tracking", "notifications")
                    ]
                }
            if resource == "pods":
                return {"items": []}
            return {"spec": {"replicas": replicas}}

        runtime.get.side_effect = get
        return runtime

    def test_resume_does_not_bootstrap_or_rerun_migrations_and_refuses_missing_success(self):
        runtime = self.runtime(0)
        with tempfile.TemporaryDirectory() as directory:
            result = a1.lifecycle(runtime, Path(directory), "resume")
            self.assertTrue(result["scenario_passed"])
            self.assertEqual(runtime.kubectl.call_count, 8)
            self.assertTrue(all(call.args[0] == "scale" for call in runtime.kubectl.call_args_list))
            original = runtime.get.side_effect
            runtime.get.side_effect = (
                lambda name: {"items": []} if name == "jobs" else original(name)
            )
            runtime.kubectl.reset_mock()
            with self.assertRaisesRegex(Failure, "MIGRATIONS_NOT_COMPLETED"):
                a1.lifecycle(runtime, Path(directory), "resume")
            runtime.kubectl.assert_not_called()

    def test_pause_scales_only_named_resources_then_stops_dedicated_node_without_delete(self):
        runtime = self.runtime(1)
        with tempfile.TemporaryDirectory() as directory:
            result = a1.lifecycle(runtime, Path(directory), "pause")
            self.assertTrue(result["data_preserved"])
            self.assertEqual(runtime.kubectl.call_count, 8)
            self.assertTrue(
                all(call.args[-1] == "--replicas=0" for call in runtime.kubectl.call_args_list)
            )
            runtime.command.assert_called_once_with(
                [config().docker, "stop", "--timeout", "30", config().node], timeout=45
            )


if __name__ == "__main__":
    unittest.main()
