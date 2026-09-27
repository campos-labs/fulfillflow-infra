"""Offline safety and capture checks; never launches Docker."""

import json
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts import observability_pilot as pilot
from scripts.scale_contract import cluster_name


class PilotTests(unittest.TestCase):
    def test_environment_is_distinct_and_legacy_names_preserved(self):
        self.assertEqual(cluster_name("observability-v1"), "fulfillflow-observe-01")
        self.assertEqual(cluster_name(""), "fulfillflow-scale-01")
        self.assertEqual(cluster_name("comparison-v1"), "fulfillflow-scale-compare-01")
        with self.assertRaises(RuntimeError):
            cluster_name("observability-v2")

    def test_log_projection_drops_payload_and_nonstructured_text(self):
        row = {
            "timestamp": "now",
            "service": "core",
            "stage": "process",
            "outcome": "DONE",
            "message_id": "one",
            "password": "secret",
            "body": "private",
        }
        result = pilot.project_logs("unsafe exception\n" + json.dumps(row) + "\n[]\n")
        self.assertEqual(result["ignored_lines"], 2)
        self.assertEqual(result["records"][0]["message_id"], "one")
        self.assertNotIn("secret", json.dumps(result))
        self.assertNotIn("private", json.dumps(result))

    def test_no_records_is_not_fabricated_coverage(self):
        self.assertEqual(pilot.project_logs("not json")["records"], [])

    def test_memory_and_power_guard(self):
        with (
            patch.object(
                pilot.psutil, "sensors_battery", return_value=SimpleNamespace(power_plugged=True)
            ),
            patch.object(
                pilot.psutil, "virtual_memory", return_value=SimpleNamespace(available=4 * 1024**3)
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "HOST_MEMORY"):
                pilot.guard(5)
            self.assertEqual(pilot.guard(2)["available_gib"], 4)
        with (
            patch.object(
                pilot.psutil, "sensors_battery", return_value=SimpleNamespace(power_plugged=False)
            ),
            patch.object(
                pilot.psutil, "virtual_memory", return_value=SimpleNamespace(available=8 * 1024**3)
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "HOST_ON_BATTERY"):
                pilot.guard(5)

    def test_existing_output_refused_before_any_docker_call(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot, "CLUSTER", pilot.EXPECTED_CLUSTER),
            patch.object(pilot.env, "preflight") as preflight,
        ):
            with self.assertRaisesRegex(RuntimeError, "EXCLUSIVE_PATHS"):
                pilot.execute(Path(directory) / "private", Path(directory))
            preflight.assert_not_called()

    def test_low_entry_memory_starts_no_environment(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot, "CLUSTER", pilot.EXPECTED_CLUSTER),
            patch.object(pilot, "guard", side_effect=RuntimeError("HOST_MEMORY_BELOW_GUARD")),
            patch.object(pilot.env, "preflight") as preflight,
        ):
            with self.assertRaisesRegex(RuntimeError, "HOST_MEMORY"):
                pilot.execute(Path(directory) / "private", Path(directory) / "output")
            preflight.assert_not_called()
            self.assertFalse((Path(directory) / "output").exists())

    def test_bootstrap_failure_stops_only_dedicated_node_and_does_not_retry(self):
        commands = []

        def command(args, **kwargs):
            commands.append(args)
            if args[0] == "git":
                return "source"
            if args[1] == "inspect":
                return json.dumps(
                    [
                        {
                            "Id": "owned-node",
                            "Config": {"Labels": {"io.x-k8s.kind.cluster": pilot.EXPECTED_CLUSTER}},
                            "State": {"Running": False},
                        }
                    ]
                )
            return ""

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot, "CLUSTER", pilot.EXPECTED_CLUSTER),
            patch.object(pilot, "guard", return_value={}),
            patch.object(pilot.env, "preflight", return_value={}),
            patch.object(pilot.env, "command", side_effect=command),
            patch.object(
                pilot, "stage", side_effect=RuntimeError("STAGE_FAILED_BOOTSTRAP")
            ) as stage,
        ):
            output = Path(directory) / "output"
            self.assertEqual(pilot.execute(Path(directory) / "private", output), 1)
            stage.assert_called_once()
            self.assertFalse(json.loads((output / "summary.json").read_bytes())["complete"])
            self.assertIn(["docker", "stop", "--timeout", "30", "owned-node"], commands)
            self.assertFalse(any("rm" in c or "delete" in c for c in commands))

    def test_flow_offers_once_and_preserves_unexpected_failure(self):
        for fail in (False, True):
            with (
                self.subTest(fail=fail),
                tempfile.TemporaryDirectory() as directory,
                ExitStack() as stack,
            ):
                root = Path(directory)
                private = root / "private"
                output = root / "output"
                private.mkdir()
                output.mkdir()
                (private / "identity.json").write_text(
                    json.dumps({"container_id": "node", "namespace_uid": "ns"})
                )
                (private / "values.json").write_text(json.dumps({"alpha": "test-only"}))
                node = {
                    "Id": "node",
                    "Config": {"Labels": {"io.x-k8s.kind.cluster": pilot.CLUSTER}},
                }
                stack.enter_context(
                    patch.object(pilot.env, "command", return_value=json.dumps([node]))
                )

                def kubectl(_private, args, **kwargs):
                    if args[0] == "get":
                        return json.dumps({"metadata": {"uid": "ns"}})
                    if args[0] == "logs":
                        return json.dumps(
                            {
                                "timestamp": "now",
                                "service": "core",
                                "stage": "process",
                                "outcome": "DONE",
                            }
                        )
                    return ""

                stack.enter_context(patch.object(pilot.env, "kubectl", side_effect=kubectl))
                for name in ("wait_api", "verify_images", "RuntimeConfig", "Runtime"):
                    stack.enter_context(patch.object(pilot, name))
                stack.enter_context(patch.object(pilot.env, "executable", return_value="docker"))
                stack.enter_context(
                    patch.object(
                        pilot,
                        "pod_identities",
                        return_value={
                            name: {"name": name, "uid": name, "restart_count": 1}
                            for name in pilot.WORKERS
                        },
                    )
                )
                stack.enter_context(
                    patch.object(
                        pilot, "tunnel", return_value=nullcontext(("http://127.0.0.1:8000", {}))
                    )
                )
                http = stack.enter_context(patch.object(pilot, "HttpTransport"))
                http.return_value.return_value.status = 200
                verifier = Mock(event_id="event")
                verifier.prepare.return_value = ("order", "shipment", "code")
                verifier.get.return_value = {"items": [], "total": 0}
                verifier.webhook.return_value = (b"synthetic", {})
                verifier.admit.return_value = ("inbox", "/inbox")
                verifier.tracking.return_value = "event"
                verifier.notifications.return_value = "notification"
                verifier.summary.side_effect = lambda success, error: {
                    "success": success,
                    "error": error,
                }
                stack.enter_context(patch.object(pilot, "ObservedVerifier", return_value=verifier))
                if fail:
                    verifier.final_business.side_effect = RuntimeError("test failure")
                    with self.assertRaisesRegex(RuntimeError, "test failure"):
                        pilot.flow(private, output)
                else:
                    pilot.flow(private, output)
                verifier.admit.assert_called_once()
                verifier.run.assert_not_called()
                result = json.loads((output / "functional.json").read_bytes())
                self.assertEqual(result["success"], not fail)
                self.assertTrue((output / "worker-records.json").is_file())

    def test_startup_wait_requires_three_equal_ready_observations(self):
        identity = {"core-worker": {"uid": "one", "restart_count": 1}}
        with patch.object(
            pilot,
            "pod_identities",
            side_effect=[RuntimeError("WORKER_NOT_STABLE"), identity, identity, identity],
        ) as read:
            sleep = Mock()
            self.assertEqual(pilot.wait_workers(None, None, samples=4, sleep=sleep), identity)
            self.assertEqual(read.call_count, 4)
            self.assertEqual(sleep.call_count, 3)

    def test_startup_wait_is_bounded_and_does_not_hide_command_errors(self):
        with patch.object(pilot, "pod_identities", side_effect=RuntimeError("WORKER_NOT_STABLE")):
            with self.assertRaisesRegex(RuntimeError, "WORKER_STARTUP_TIMEOUT"):
                pilot.wait_workers(None, None, samples=3, sleep=Mock())
        with patch.object(pilot, "pod_identities", side_effect=RuntimeError("COMMAND_FAILED")):
            with self.assertRaisesRegex(RuntimeError, "COMMAND_FAILED"):
                pilot.wait_workers(None, None, sleep=Mock())

    def test_resume_rejects_any_possible_offer_before_docker_access(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot.env, "command") as command,
        ):
            source = Path(directory)
            (source / "protocol.json").write_text(
                json.dumps({"infrastructure_sha": "e1a46246012acbb858c049e60b7048c4b67524b3"})
            )
            (source / "flow-error.json").write_text(json.dumps({"error": "WORKER_NOT_STABLE"}))
            (source / "event").mkdir()
            with self.assertRaisesRegex(RuntimeError, "RESUME_MAY_HAVE_OFFERED"):
                pilot.resume_identity(source, source)
            command.assert_not_called()

    def test_resume_cannot_be_reused_with_another_output(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot.env, "command") as command,
        ):
            private = Path(directory)
            (private / "observability-resume.claim").write_text("claimed")
            with self.assertRaisesRegex(RuntimeError, "RESUME_ALREADY_CLAIMED"):
                pilot.resume_identity(private, private / "absent")
            command.assert_not_called()

    def test_forwarding_preflight_is_get_only_and_requires_empty_valid_result(self):
        verifier = Mock(event_id="fresh-event")
        verifier.get.return_value = {"items": [], "total": 0}
        pilot.check_forwarding(verifier)
        self.assertIn("fresh-event", verifier.get.call_args.args[0])
        verifier.prepare.assert_not_called()
        verifier.admit.assert_not_called()
        verifier.get.return_value = {"items": [], "total": 1}
        with self.assertRaises(pilot.Failure):
            pilot.check_forwarding(verifier)

    def test_memory_failure_terminates_owned_child(self):
        child = Mock()
        child.poll.return_value = None
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(pilot.subprocess, "Popen", return_value=child),
            patch.object(pilot, "guard", side_effect=RuntimeError("HOST_MEMORY_BELOW_GUARD")),
            patch.object(pilot, "terminate_child") as terminate,
        ):
            with self.assertRaisesRegex(RuntimeError, "HOST_MEMORY"):
                pilot.stage("flow", Path(directory), Path(directory))
            terminate.assert_called_once_with(child)


if __name__ == "__main__":
    unittest.main()
