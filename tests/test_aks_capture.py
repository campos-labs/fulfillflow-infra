import copy
import importlib.util
import json
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location(
    "capture_persistence",
    Path(__file__).resolve().parents[1] / "scripts/azure/capture_persistence.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            key: f"00000000-0000-0000-0000-{i:012d}"
            for i, key in enumerate(
                ("system_namespace_uid", "order_id", "shipment_id", "event_id", "notification_id"),
                1,
            )
        }
        self.target.update(
            window="test-window",
            api_server="https://synthetic.example",
            cluster_id="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/synthetic/providers/Microsoft.ContainerService/managedClusters/synthetic",
        )
        self.records = [
            {"clusters": [{"cluster": {"server": self.target["api_server"]}}]},
            {"metadata": {"uid": self.target["system_namespace_uid"]}},
            {
                "metadata": {
                    "uid": "pod",
                    "labels": {"fulfillflow.io/window": "test-window"},
                    "ownerReferences": [
                        {"kind": "StatefulSet", "name": "postgres", "controller": True}
                    ],
                },
                "spec": {"volumes": [{"persistentVolumeClaim": {"claimName": "data-postgres-0"}}]},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"uid": "pvc"},
                "status": {"phase": "Bound"},
                "spec": {"volumeName": "pv"},
            },
            {
                "metadata": {"uid": "pv"},
                "status": {"phase": "Bound"},
                "spec": {
                    "claimRef": {
                        "uid": "pvc",
                        "namespace": "fulfillflow",
                        "name": "data-postgres-0",
                    },
                    "csi": {"driver": "disk.csi.azure.com", "volumeHandle": "disk"},
                },
            },
        ]
        t = self.target
        self.responses = [
            {"id": t["order_id"], "status": "FULFILLED", "private_field": "not retained"},
            {"id": t["shipment_id"], "order_id": t["order_id"], "status": "DELIVERED"},
            {
                "total": 1,
                "items": [
                    {
                        "id": t["event_id"],
                        "application_result": "APPLIED",
                        "resulting_shipment_status": "DELIVERED",
                    }
                ],
            },
            {
                "tracking_event_id": t["event_id"],
                "notification_id": t["notification_id"],
                "processing": "DONE",
                "status": "SIMULATED",
                "required": True,
            },
        ]

    def test_capture_volume_provenance_without_mutations(self):
        kube = Mock(side_effect=self.records)
        result = m.infrastructure(self.target, kube)
        self.assertEqual(result["volume_handle"], "disk")
        self.assertTrue(all(c.args[0][0] in {"get", "config"} for c in kube.call_args_list))

    def test_wrong_server_stops_before_cluster_read(self):
        self.records[0]["clusters"][0]["cluster"]["server"] = "https://other.example"
        kube = Mock(side_effect=self.records)
        with self.assertRaises(ValueError):
            m.infrastructure(self.target, kube)
        self.assertEqual(kube.call_count, 1)

    def test_namespace_identity_changed(self):
        self.records[1]["metadata"]["uid"] = "different"
        with self.assertRaises(ValueError):
            m.infrastructure(self.target, Mock(side_effect=self.records))

    def test_invalid_window_binding_readiness_or_storage_rejected(self):
        cases = [
            (2, ("metadata", "labels", "fulfillflow.io/window"), "historical"),
            (2, ("metadata", "deletionTimestamp"), "now"),
            (3, ("status", "phase"), "Pending"),
            (4, ("spec", "claimRef", "uid"), "other"),
            (4, ("spec", "csi", "driver"), "local-path"),
        ]
        for index, keys, value in cases:
            records = copy.deepcopy(self.records)
            item = records[index]
            for key in keys[:-1]:
                item = item[key]
            item[keys[-1]] = value
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                m.infrastructure(self.target, Mock(side_effect=records))

    def test_same_known_business_and_minimal_output(self):
        get = Mock(side_effect=self.responses)
        result = m.business(self.target, get)
        self.assertEqual(result["event_id"], self.target["event_id"])
        self.assertNotIn("private_field", str(result))
        self.assertEqual(get.call_count, 4)

    def test_different_event_or_incomplete_result_rejected(self):
        for index, key, value in (
            (0, "status", "CONFIRMED"),
            (1, "order_id", "other"),
            (2, "total", 2),
            (3, "notification_id", "other"),
            (3, "processing", "PENDING"),
        ):
            records = copy.deepcopy(self.responses)
            records[index][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                m.business(self.target, Mock(side_effect=records))

    def test_path_injection_target_rejected(self):
        with self.assertRaises(ValueError):
            m.validate_target({**self.target, "event_id": "../../other"})

    def test_tunnel_uses_own_ephemeral_port_and_cleans_up(self):
        process = Mock()
        process.poll.return_value = None

        def start(command, stdout, **kwargs):
            self.assertIn(":8000", command)
            self.assertIn("127.0.0.1", command)
            stdout.write(b"Forwarding from 127.0.0.1:34567 -> 8000\n")
            stdout.flush()
            return process

        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(m.subprocess, "Popen", side_effect=start),
        ):
            with m.tunnel(["synthetic-kubectl"], Path(directory) / "tunnel.log") as (url, child):
                self.assertEqual(url, "http://127.0.0.1:34567")
                self.assertIs(child, process)
            process.terminate.assert_called_once()
            process.wait.assert_called_once()

    def test_tunnel_failure_cannot_use_other_listener(self):
        process = Mock()
        process.poll.return_value = 1
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(m.subprocess, "Popen", return_value=process),
        ):
            with self.assertRaises(ValueError):
                with m.tunnel(["synthetic-kubectl"], Path(directory) / "tunnel.log"):
                    self.fail("dead tunnel must not yield")

    def test_failed_http_preserves_status_without_body_or_retry(self):
        @contextmanager
        def fake_tunnel(prefix, log):
            process = Mock()
            process.poll.return_value = None
            yield "http://127.0.0.1:12345", process

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target.json"
            target.write_text(json.dumps(self.target))
            tool = root / "kubectl"
            tool.touch()
            config = root / "config"
            config.touch()
            output = root / "output"
            argv = [
                "capture",
                "--target",
                str(target),
                "--kubeconfig",
                str(config),
                "--kubectl",
                str(tool),
                "--context",
                "test",
                "--output",
                str(output),
            ]
            transport = Mock(return_value=Mock(status=503, body=b"private-response-body"))
            service = {"metadata": {"labels": {"fulfillflow.io/window": "test-window"}}}
            with (
                patch.object(m.sys, "argv", argv),
                patch.object(m, "infrastructure", return_value={"pod_uid": "pod"}),
                patch.object(m.subprocess, "run", return_value=Mock(stdout=json.dumps(service))),
                patch.object(m, "tunnel", fake_tunnel),
                patch.object(m, "HttpTransport", return_value=transport),
            ):
                self.assertEqual(m.main(), 1)
            transport.assert_called_once()
            query = json.loads((output / "queries.jsonl").read_text())
            self.assertEqual(query["status"], 503)
            failure = json.loads((output / "failure.json").read_text())
            self.assertEqual(failure["stage"], "business_http")
            self.assertEqual(failure["observed_responses"], 1)
            self.assertNotIn(
                "private-response-body", "".join(f.read_text() for f in output.iterdir())
            )
