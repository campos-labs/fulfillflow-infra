"""Behavioral contracts for render-only infrastructure; no cluster access."""

from __future__ import annotations

import base64
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
K8S = ROOT / "k8s"
spec = importlib.util.spec_from_file_location(
    "broker_definitions", K8S / "prepare_rabbitmq_definitions.py"
)
assert spec and spec.loader
broker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(broker)


def matches(selector, labels):
    return all(labels.get(key) == value for key, value in selector.get("matchLabels", {}).items())


class ManifestContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        executable = os.environ.get("KUBECTL") or os.environ.get("KUBECTL_PATH")
        if not executable:
            portable = (
                ROOT / ".tools" / "kubectl" / ("kubectl.exe" if os.name == "nt" else "kubectl")
            )
            executable = str(portable) if portable.exists() else shutil.which("kubectl")
        if not executable:
            raise RuntimeError("kubectl 1.35.3 is required; set KUBECTL to the pinned executable")
        result = subprocess.run(
            [executable, "kustomize", str(K8S / "overlays/example")],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        cls.documents = list(yaml.safe_load_all(result.stdout))
        cls.by_key = {(item["kind"], item["metadata"]["name"]): item for item in cls.documents}
        cls.workloads = [
            item for item in cls.documents if item["kind"] in {"Deployment", "StatefulSet", "Job"}
        ]
        cls.policies = [item for item in cls.documents if item["kind"] == "NetworkPolicy"]

    def test_reduced_profile_changes_only_cpu_requests_and_profile_annotation(self):
        executable = (
            os.environ.get("KUBECTL")
            or os.environ.get("KUBECTL_PATH")
            or str(ROOT / ".tools/kubectl" / ("kubectl.exe" if os.name == "nt" else "kubectl"))
        )
        rendered = subprocess.run(
            [executable, "kustomize", str(K8S / "overlays/reduced-functional")],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        reduced = {
            (d["kind"], d["metadata"]["name"]): d for d in yaml.safe_load_all(rendered.stdout)
        }
        self.assertEqual(set(reduced), set(self.by_key))
        runtime_cpu = 0
        for key, original in self.by_key.items():
            expected = copy.deepcopy(original)
            expected["metadata"].setdefault("annotations", {})[
                "fulfillflow.io/resource-profile"
            ] = "reduced-functional-unverified"
            if key[0] in {"Deployment", "StatefulSet", "Job"}:
                expected["spec"]["template"]["metadata"].setdefault("annotations", {})[
                    "fulfillflow.io/resource-profile"
                ] = "reduced-functional-unverified"
                cpu = (
                    "750m"
                    if key[1] == "postgres"
                    else "250m"
                    if key[1] == "rabbitmq" or key[0] == "Job"
                    else "150m"
                )
                expected["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"][
                    "cpu"
                ] = cpu
                if key[0] != "Job":
                    runtime_cpu += int(cpu[:-1])
            self.assertEqual(reduced[key], expected, key)
        self.assertEqual(runtime_cpu, 1900)

    def container(self, name, kind="Deployment"):
        return self.by_key[kind, name]["spec"]["template"]["spec"]["containers"][0]

    def test_example_has_all_processes_and_cannot_schedule(self):
        self.assertEqual(len(self.workloads), 11)
        deployments = {
            item["metadata"]["name"] for item in self.documents if item["kind"] == "Deployment"
        }
        self.assertEqual(
            deployments,
            {
                "core",
                "tracking",
                "notifications",
                "core-worker",
                "tracking-worker",
                "notifications-worker",
            },
        )
        for item in self.workloads:
            self.assertEqual(
                item["metadata"]["annotations"]["fulfillflow.io/validation-only"], "true"
            )
            pod = item["spec"]["template"]["spec"]
            self.assertEqual(
                pod["nodeSelector"],
                {"fulfillflow.io/deployment-approved": "example-never-schedule"},
            )
            if item["kind"] != "Job":
                self.assertEqual(item["spec"]["replicas"], 1)
            else:
                self.assertEqual(item["spec"]["backoffLimit"], 0)
                self.assertEqual(item["spec"]["activeDeadlineSeconds"], 300)
                self.assertNotIn("ttlSecondsAfterFinished", item["spec"])

    def test_images_are_pinned_and_runtime_is_explicitly_invalid(self):
        for item in self.workloads:
            image = item["spec"]["template"]["spec"]["containers"][0]["image"]
            self.assertRegex(image, r"@sha256:[a-f0-9]{64}$")
            if item["kind"] != "StatefulSet":
                self.assertEqual(
                    image, "example.azurecr.io.invalid/fulfillflow/runtime@sha256:" + "0" * 64
                )
        self.assertEqual(
            self.container("postgres", "StatefulSet")["image"],
            "postgres:18-trixie@sha256:4ef4dbc939d61acea57712655ddb4b4ab27419c913f94cca0cd57cb3ea3c2280",
        )
        self.assertEqual(
            self.container("rabbitmq", "StatefulSet")["image"],
            "rabbitmq:4.2.4-alpine@sha256:d1b24a78c1ace826771eb8585d8f30315a64f1aad4d1fe6fcd9b4435cccc16f4",
        )

    def test_worker_health_never_restarts_on_dependency_failure(self):
        for role in ("core", "tracking", "notifications"):
            worker = self.container(role + "-worker")
            self.assertNotIn("startupProbe", worker)
            self.assertNotIn("livenessProbe", worker)
            self.assertNotIn("ports", worker)
            self.assertEqual(
                worker["readinessProbe"]["exec"]["command"],
                ["python", "-m", "fulfillflow.messaging.health", "--service", role],
            )
            self.assertEqual(worker["command"], ["python", "-m", f"fulfillflow.{role}.worker"])
            api = self.container(role)
            for probe in ("startupProbe", "livenessProbe"):
                self.assertEqual(api[probe]["httpGet"]["path"], "/health/live")
            self.assertEqual(api["readinessProbe"]["httpGet"]["path"], "/health/ready")

    def test_required_secrets_are_scoped_without_literal_credentials(self):
        self.assertFalse(any(item["kind"] == "Secret" for item in self.documents))
        role_keys = {
            "core": {"INTERNAL_API_SECRET", "SESSION_SECRET", "NOTIFICATIONS_API_SECRET"},
            "tracking": {
                "INTERNAL_API_SECRET",
                "CARRIER_ALPHA_WEBHOOK_SECRET",
                "CARRIER_BETA_WEBHOOK_SECRET",
            },
            "notifications": {"INTERNAL_API_SECRET"},
        }
        for role, keys in role_keys.items():
            for worker in (False, True):
                entries = self.container(role + "-worker" if worker else role)["env"]
                refs = {
                    entry["name"]: entry["valueFrom"]["secretKeyRef"]
                    for entry in entries
                    if "valueFrom" in entry
                }
                self.assertEqual(
                    set(refs), keys | {"DATABASE_URL"} | ({"AMQP_URL"} if worker else set())
                )
                for name, ref in refs.items():
                    self.assertIs(ref["optional"], False)
                    expected = role + (
                        "-database"
                        if name == "DATABASE_URL"
                        else "-amqp"
                        if name == "AMQP_URL"
                        else "-runtime"
                    )
                    self.assertEqual(ref["name"], expected)
                pool = next(entry["value"] for entry in entries if entry["name"] == "DB_POOL_SIZE")
                self.assertEqual(pool, "3" if worker else "2")
            job = self.container("migrate-" + role, "Job")
            refs = [
                entry["valueFrom"]["secretKeyRef"] for entry in job["env"] if "valueFrom" in entry
            ]
            self.assertEqual(
                refs, [{"name": role + "-database", "key": "DATABASE_URL", "optional": False}]
            )
            self.assertEqual(
                job["command"], ["alembic", "-c", f"alembic_{role}.ini", "upgrade", "head"]
            )

    def test_volume_identity_and_nonroot_writable_paths(self):
        for item in self.workloads:
            name = item["metadata"]["name"]
            pod = item["spec"]["template"]["spec"]
            self.assertFalse(pod["automountServiceAccountToken"])
            self.assertGreaterEqual(pod["terminationGracePeriodSeconds"], 20)
            uid, gid = (
                (999, 999)
                if name == "postgres"
                else (100, 101)
                if name == "rabbitmq"
                else (10001, 10001)
            )
            self.assertEqual(pod["securityContext"]["runAsUser"], uid)
            self.assertEqual(pod["securityContext"]["runAsGroup"], gid)
            self.assertEqual(pod["securityContext"]["fsGroup"], gid)
            c = pod["containers"][0]
            self.assertTrue(c["securityContext"]["readOnlyRootFilesystem"])
            self.assertFalse(c["securityContext"]["allowPrivilegeEscalation"])
            self.assertEqual(c["securityContext"]["capabilities"]["drop"], ["ALL"])
            self.assertIn({"name": "tmp", "mountPath": "/tmp"}, c["volumeMounts"])
        pg = self.container("postgres", "StatefulSet")
        self.assertIn({"name": "data", "mountPath": "/var/lib/postgresql"}, pg["volumeMounts"])
        self.assertIn({"name": "PGDATA", "value": "/var/lib/postgresql/18/docker"}, pg["env"])
        self.assertIn(
            {"name": "RABBITMQ_NODENAME", "value": "rabbit@rabbitmq-0"},
            self.container("rabbitmq", "StatefulSet")["env"],
        )
        for name in ("postgres", "rabbitmq"):
            stateful = self.by_key["StatefulSet", name]["spec"]
            self.assertEqual(stateful["serviceName"], name)
            self.assertEqual(
                stateful["persistentVolumeClaimRetentionPolicy"],
                {"whenDeleted": "Retain", "whenScaled": "Retain"},
            )
        self.assertEqual(
            self.by_key["StorageClass", "fulfillflow-retain"]["reclaimPolicy"], "Retain"
        )

    def test_fixed_resource_budget_and_clusterip_only(self):
        for item in self.workloads:
            name = item["metadata"]["name"]
            resources = item["spec"]["template"]["spec"]["containers"][0]["resources"]
            expected = (
                {"cpu": "2", "memory": "2560Mi"}
                if name == "postgres"
                else {"cpu": "500m", "memory": "512Mi"}
                if name == "rabbitmq"
                else {"cpu": "500m", "memory": "384Mi"}
            )
            self.assertEqual(resources["limits"], expected)
            self.assertEqual(resources["requests"], expected)
            if item["kind"] == "Deployment":
                self.assertEqual(
                    item["spec"]["strategy"]["rollingUpdate"], {"maxSurge": 0, "maxUnavailable": 1}
                )
        for item in self.documents:
            self.assertNotIn(item["kind"], {"Ingress", "HorizontalPodAutoscaler"})
            if item["kind"] == "Service":
                self.assertEqual(item["spec"]["type"], "ClusterIP")
                self.assertFalse(item["metadata"]["name"].endswith("worker"))

    def flow_allowed(self, source, destination, port):
        def labels_for(name):
            return next(
                item["spec"]["template"]["metadata"]["labels"]
                for item in self.workloads
                if item["metadata"]["name"] == name
            )

        source_labels, target_labels = labels_for(source), labels_for(destination)
        for direction, own, other, peer_key in (
            ("Egress", source_labels, target_labels, "to"),
            ("Ingress", target_labels, source_labels, "from"),
        ):
            selected = [
                policy["spec"]
                for policy in self.policies
                if direction in policy["spec"]["policyTypes"]
                and matches(policy["spec"]["podSelector"], own)
            ]
            permitted = False
            for policy in selected:
                for rule in policy.get(direction.lower(), []):
                    port_matches = any(
                        p["port"] == port and p.get("protocol", "TCP") == "TCP"
                        for p in rule.get("ports", [])
                    )
                    peer_matches = any(
                        "namespaceSelector" not in peer
                        and matches(peer.get("podSelector", {}), other)
                        for peer in rule.get(peer_key, [])
                    )
                    permitted |= port_matches and peer_matches
            if selected and not permitted:
                return False
        return True

    def test_network_policies_allow_required_flows_and_reject_others(self):
        deny = self.by_key["NetworkPolicy", "default-deny"]["spec"]
        self.assertEqual(deny["podSelector"], {"matchLabels": {}})
        self.assertEqual(set(deny["policyTypes"]), {"Ingress", "Egress"})
        for role in ("core", "tracking", "notifications"):
            for name in (role, role + "-worker", "migrate-" + role):
                self.assertTrue(self.flow_allowed(name, "postgres", 5432), name)
            self.assertTrue(self.flow_allowed(role + "-worker", "rabbitmq", 5672))
            self.assertFalse(self.flow_allowed(role, "rabbitmq", 5672))
            self.assertFalse(self.flow_allowed("migrate-" + role, "rabbitmq", 5672))
            self.assertFalse(self.flow_allowed(role + "-worker", "core", 8000))
        for source, destination in (
            ("core", "tracking"),
            ("core", "notifications"),
            ("tracking", "core"),
        ):
            self.assertTrue(self.flow_allowed(source, destination, 8000))
        self.assertFalse(self.flow_allowed("notifications", "core", 8000))
        dns = self.by_key["NetworkPolicy", "dns"]["spec"]["egress"][0]
        self.assertEqual(
            dns["to"],
            [
                {
                    "namespaceSelector": {
                        "matchLabels": {"kubernetes.io/metadata.name": "kube-system"}
                    },
                    "podSelector": {"matchLabels": {"k8s-app": "kube-dns"}},
                }
            ],
        )
        self.assertEqual(
            {(port["protocol"], port["port"]) for port in dns["ports"]}, {("TCP", 53), ("UDP", 53)}
        )

    def test_initialization_preserves_database_owner_isolation(self):
        scripts = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (K8S / "base/foundations/assets").glob("*.sh")
        )
        for role in ("core", "tracking", "notifications"):
            self.assertIn(f"CREATE DATABASE fulfillflow_{role} OWNER fulfillflow_{role};", scripts)
            self.assertIn(f"REVOKE ALL ON DATABASE fulfillflow_{role} FROM PUBLIC;", scripts)
            self.assertIn(f"\\getenv {role}_password {role.upper()}_DB_PASSWORD", scripts)
        self.assertNotIn("--set=core_password", scripts)
        self.assertNotIn("--set=tracking_password", scripts)
        self.assertNotIn("--set=notifications_password", scripts)
        for path in (K8S / "base/foundations/assets").glob("*.sh"):
            self.assertNotIn(b"\r", path.read_bytes())


class BrokerDefinitionsContracts(unittest.TestCase):
    def passwords(self):
        return {
            role: f"synthetic-unit-input-{role}-" + "x" * 32
            for role in ("core", "tracking", "notifications")
        }

    def test_template_matches_frozen_topology_without_local_hashes(self):
        self.assertEqual(
            hashlib.sha256(broker.TEMPLATE.read_bytes()).hexdigest(),
            "daa6213bdb06bb99c7d24274aad1cc8c05b98ea4a18d966dcbad6cb1fc769b4b",
        )
        template = json.loads(broker.TEMPLATE.read_text(encoding="utf-8"))
        self.assertTrue(
            all(
                "password" not in user and "password_hash" not in user for user in template["users"]
            )
        )
        self.assertEqual(
            {queue["name"] for queue in template["queues"]},
            {
                "tracking.apply.v1.queue",
                "tracking.result.v1.queue",
                "shipment.status_changed.v1.queue",
            },
        )

    def test_generated_hashes_authenticate_supplied_owner_password_only(self):
        passwords = self.passwords()
        result = broker.build_definitions(passwords)
        broker.validate_definitions(result)
        for user in result["users"]:
            raw = base64.b64decode(user["password_hash"])
            self.assertEqual(
                raw[4:], hashlib.sha256(raw[:4] + passwords[user["name"]].encode()).digest()
            )
            self.assertNotIn("password", user)
        for role in passwords:
            self.assertNotIn(passwords[role], json.dumps(result))

    def test_acl_drift_plaintext_and_malformed_hash_are_rejected(self):
        original = broker.build_definitions(self.passwords())
        for mutate in (
            lambda value: value["permissions"][0].update(read=".*"),
            lambda value: value["users"][0].update(password="synthetic"),
            lambda value: value["users"][0].update(password_hash="invalid"),
            lambda value: value["users"].append(copy.deepcopy(value["users"][0])),
        ):
            changed = copy.deepcopy(original)
            mutate(changed)
            with self.assertRaises(ValueError):
                broker.validate_definitions(changed)

    def test_invalid_owner_input_is_rejected(self):
        for value in (
            {},
            ["core", "tracking", "notifications"],
            {"core": "a" * 32},
            dict.fromkeys(broker.OWNERS, "a" * 32),
            dict.fromkeys(broker.OWNERS, "short"),
        ):
            with self.assertRaises(ValueError):
                broker.build_definitions(value)

    def test_cli_creates_new_protected_output_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "passwords.json"
            output_path = Path(folder) / "definitions.json"
            input_path.write_text(json.dumps(self.passwords()), encoding="utf-8")
            arguments = ["--passwords-file", str(input_path), "--output", str(output_path)]
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(broker.main(arguments), 0)
                before = output_path.read_bytes()
                self.assertEqual(broker.main(arguments), 1)
                self.assertEqual(output_path.read_bytes(), before)
            broker.validate_definitions(json.loads(before))
            for password in self.passwords().values():
                self.assertNotIn(password, output.getvalue())
            for user in json.loads(before)["users"]:
                self.assertNotIn(user["password_hash"], output.getvalue())

    def test_cli_refuses_repository_output_and_malformed_input(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "passwords.json"
            output_path = Path(folder) / "definitions.json"
            input_path.write_text("not-json", encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                self.assertEqual(
                    broker.main(
                        [
                            "--passwords-file",
                            str(input_path),
                            "--output",
                            str(K8S / "forbidden.json"),
                        ]
                    ),
                    2,
                )
                self.assertEqual(
                    broker.main(
                        ["--passwords-file", str(input_path), "--output", str(output_path)]
                    ),
                    1,
                )
            self.assertFalse(output_path.exists())
            self.assertFalse((K8S / "forbidden.json").exists())
            self.assertNotIn("Traceback", output.getvalue())


if __name__ == "__main__":
    unittest.main()
