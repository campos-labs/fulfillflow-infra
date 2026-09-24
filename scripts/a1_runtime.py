"""Bounded, explicit access to the existing single-node Kind laboratory."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from scripts.verify_flow import EXPECTED_APPLICATION_SHA, Failure

ROOT = Path(__file__).resolve().parents[1]
WORKLOADS = (
    "core",
    "core-worker",
    "tracking",
    "tracking-worker",
    "notifications",
    "notifications-worker",
)
TARGET = "notifications-worker"
MARKER = "fulfillflow.io/a1-attempt"


def check(condition: bool, code: str) -> None:
    if not condition:
        raise Failure(code, 2)


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_json(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


@dataclass(frozen=True)
class Config:
    kubectl: str
    docker: str
    kubeconfig: str
    context: str
    namespace: str
    namespace_uid: str
    node: str
    image: str
    image_id: str
    operation_seconds: float = 600
    rollout_seconds: float = 90
    flow_seconds: float = 90
    poll_seconds: float = 1

    @classmethod
    def load(cls, path: Path) -> Config:
        try:
            result = cls(**json.loads(path.read_text(encoding="utf-8")))
            result.validate()
            return result
        except (TypeError, ValueError, KeyError, AttributeError):
            raise Failure("INVALID_OPERATION_CONFIG", 2) from None

    def validate(self) -> None:
        for name in (self.kubectl, self.docker, self.kubeconfig):
            check(Path(name).is_absolute() and Path(name).is_file(), "ABSOLUTE_FILE_REQUIRED")
        check(self.context.startswith("kind-"), "LOCAL_CONTEXT_REQUIRED")
        check(self.node == self.context[5:] + "-control-plane", "NODE_CONTEXT_MISMATCH")
        check(self.namespace == "fulfillflow", "DEDICATED_NAMESPACE_REQUIRED")
        UUID(self.namespace_uid)
        check(self.image == "fulfillflow-kind-runtime:source-9e3a135a00db", "FROZEN_IMAGE_REQUIRED")
        check(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", self.image_id)), "IMAGE_ID_REQUIRED")
        for value, low, high in (
            (self.operation_seconds, 30, 900),
            (self.rollout_seconds, 5, 300),
            (self.flow_seconds, 5, 300),
            (self.poll_seconds, 0.1, 5),
        ):
            check(
                type(value) in (int, float) and math.isfinite(value) and low <= value <= high,
                "INVALID_DEADLINE",
            )

    def identity(self) -> dict:
        return {
            "context": self.context,
            "namespace": self.namespace,
            "namespace_uid": self.namespace_uid,
            "node": self.node,
            "image": self.image,
            "image_id": self.image_id,
        }


@contextmanager
def environment_lock(config: Config):
    # OS-owned lock is released on process death. Keep the inode; unlink races are unsafe.
    path = Path(tempfile.gettempdir()) / f"fulfillflow-a1-{config.namespace_uid}.lock"
    stream = path.open("a+b")
    try:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise Failure("ENVIRONMENT_BUSY", 2) from None
        yield
    finally:
        stream.close()


class Runtime:
    def __init__(self, config: Config, *, clock=time.monotonic, sleep=time.sleep):
        self.config, self.clock, self.sleep = config, clock, sleep
        self.deadline = clock() + config.operation_seconds
        self.last_snapshot = None

    def remaining(self) -> float:
        value = self.deadline - self.clock()
        if value <= 0:
            raise Failure("OPERATION_DEADLINE", 5)
        return value

    def command(self, arguments: list[str], *, timeout=30, stdin=None) -> str:
        try:
            result = subprocess.run(
                arguments,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=min(timeout, self.remaining()),
            )
        except subprocess.TimeoutExpired:
            raise Failure("SUBPROCESS_TIMEOUT_OUTCOME_UNKNOWN", 5) from None
        except OSError:
            raise Failure("SUBPROCESS_UNAVAILABLE", 2) from None
        if result.returncode:
            raise Failure(f"SUBPROCESS_EXIT_{result.returncode}", 3)
        return result.stdout

    def prefix(self) -> list[str]:
        c = self.config
        return [
            c.kubectl,
            "--kubeconfig",
            c.kubeconfig,
            "--context",
            c.context,
            "--namespace",
            c.namespace,
            "--request-timeout=15s",
        ]

    def kubectl(self, *arguments: str) -> str:
        return self.command(self.prefix() + list(arguments))

    def get(self, resource: str, *arguments: str) -> dict:
        return json.loads(self.kubectl("get", resource, *arguments, "-o", "json"))

    def preflight(self) -> None:
        view = json.loads(self.kubectl("config", "view", "--minify", "-o", "json"))
        server = view["clusters"][0]["cluster"]["server"]
        check(bool(re.fullmatch(r"https://127\.0\.0\.1:\d+", server)), "LOOPBACK_API_REQUIRED")
        check(
            self.get("namespace/" + self.config.namespace)["metadata"]["uid"]
            == self.config.namespace_uid,
            "NAMESPACE_IDENTITY_MISMATCH",
        )
        versions = json.loads(self.kubectl("version", "--client", "-o", "json"))
        lock = json.loads((ROOT / "config/toolchain.json").read_text())
        check(
            versions["clientVersion"]["gitVersion"] == lock["kubectl"], "KUBECTL_VERSION_MISMATCH"
        )
        check(not self.get("hpa")["items"], "AUTOSCALER_NOT_ALLOWED")
        nodes = self.get("nodes")["items"]
        check(
            len(nodes) == 1 and nodes[0]["metadata"]["name"] == self.config.node,
            "NODE_IDENTITY_MISMATCH",
        )

    def inventory(self) -> dict:
        deployments = self.get("deployments")["items"]
        check(
            {x["metadata"]["name"] for x in deployments} == set(WORKLOADS), "WORKLOAD_SET_MISMATCH"
        )
        result = {}
        for item in deployments:
            check(
                item["metadata"].get("annotations", {}).get("fulfillflow.io/application-source")
                == EXPECTED_APPLICATION_SHA,
                "APPLICATION_SOURCE_MISMATCH",
            )
            template = item["spec"]["template"]
            validate_template(template, self.config)
            result[item["metadata"]["name"]] = {
                "uid": item["metadata"]["uid"],
                "replicas": item["spec"]["replicas"],
                "template_hash": digest(template),
            }
        return result

    def snapshot(self) -> dict:
        deployment = self.get("deployment/" + TARGET)
        validate_template(deployment["spec"]["template"], self.config)
        uid = deployment["metadata"]["uid"]
        replicasets = self.get("replicasets", "-l", "app.kubernetes.io/name=" + TARGET)["items"]
        owned = {r["metadata"]["uid"] for r in replicasets if owned_by(r, uid)}
        pods = self.get("pods", "-l", "app.kubernetes.io/name=" + TARGET)["items"]
        pods = [p for p in pods if any(owned_by(p, owner) for owner in owned)]
        result = {
            "observed_at": datetime.now(UTC).isoformat(),
            "deployment_uid": uid,
            "generation": deployment["metadata"]["generation"],
            "attempt": deployment["spec"]["template"]["metadata"]
            .get("annotations", {})
            .get(MARKER),
            "resource_version": deployment["metadata"]["resourceVersion"],
            "template_hash": digest(deployment["spec"]["template"]),
            "revision": deployment["metadata"]
            .get("annotations", {})
            .get("deployment.kubernetes.io/revision"),
            "desired": deployment["spec"]["replicas"],
            "status": {
                k: v
                for k, v in deployment.get("status", {}).items()
                if k
                in {
                    "observedGeneration",
                    "replicas",
                    "updatedReplicas",
                    "availableReplicas",
                    "readyReplicas",
                    "unavailableReplicas",
                }
            },
            "pods": [pod_record(p) for p in pods],
        }
        self.last_snapshot = result
        return result

    def wait_target(self, template_hash: str, *, allow_fault=False) -> dict:
        end = min(self.deadline, self.clock() + self.config.rollout_seconds)
        while True:
            record = self.snapshot()
            check(record["template_hash"] == template_hash, "CANDIDATE_CHANGED")
            if converged(record, self.config):
                return record
            if allow_fault and candidate_crashed(record, self.config):
                return record
            if self.clock() >= end:
                raise Failure("ROLLOUT_DEADLINE", 5)
            self.sleep(min(self.config.poll_seconds, end - self.clock()))

    def patch_template(self, deployment: dict, template: dict, destination: Path) -> None:
        validate_template(template, self.config)
        patch = [
            {"op": "test", "path": "/metadata/uid", "value": deployment["metadata"]["uid"]},
            {
                "op": "test",
                "path": "/metadata/resourceVersion",
                "value": deployment["metadata"]["resourceVersion"],
            },
            {"op": "test", "path": "/spec/template", "value": deployment["spec"]["template"]},
            {"op": "replace", "path": "/spec/template", "value": template},
        ]
        write_json(destination, patch)
        self.kubectl(
            "patch", "deployment/" + TARGET, "--type=json", "--patch-file", str(destination)
        )


def validate_template(template: dict, config: Config) -> None:
    containers = template["spec"]["containers"]
    check(len(containers) == 1 and containers[0]["image"] == config.image, "FROZEN_IMAGE_REQUIRED")
    for container in containers + template["spec"].get("initContainers", []):
        for env in container.get("env", []):
            if re.search(r"SECRET|PASSWORD|TOKEN|DATABASE_URL|AMQP_URL", env["name"]):
                check(
                    "value" not in env and "secretKeyRef" in env.get("valueFrom", {}),
                    "INLINE_SECRET_FORBIDDEN",
                )


def owned_by(item: dict, uid: str) -> bool:
    return any(
        x.get("uid") == uid and x.get("controller") is True
        for x in item["metadata"].get("ownerReferences", [])
    )


def pod_record(pod: dict) -> dict:
    statuses = pod.get("status", {}).get("containerStatuses", [])
    # Container termination messages and environment values are intentionally excluded.
    return {
        "name": pod["metadata"]["name"],
        "uid": pod["metadata"]["uid"],
        "owner_uids": [x["uid"] for x in pod["metadata"].get("ownerReferences", [])],
        "attempt": pod["metadata"].get("annotations", {}).get(MARKER),
        "deleting": bool(pod["metadata"].get("deletionTimestamp")),
        "containers": [
            {
                "name": s["name"],
                "image": s["image"],
                "image_id": s.get("imageID"),
                "ready": s.get("ready", False),
                "restarts": s.get("restartCount", 0),
                "waiting_reason": s.get("state", {}).get("waiting", {}).get("reason"),
                "exit_code": s.get("state", {})
                .get("terminated", s.get("lastState", {}).get("terminated", {}))
                .get("exitCode"),
            }
            for s in statuses
        ],
    }


def converged(record: dict, config: Config) -> bool:
    status = record["status"]
    pods = record["pods"]
    return (
        record["desired"] == 1
        and status.get("observedGeneration", 0) >= record["generation"]
        and status.get("updatedReplicas")
        == status.get("availableReplicas")
        == status.get("replicas")
        == 1
        and len(pods) == 1
        and not pods[0]["deleting"]
        and pods[0]["attempt"] == record["attempt"]
        and len(pods[0]["containers"]) == 1
        and pods[0]["containers"][0]["ready"]
        and pods[0]["containers"][0]["image_id"] == config.image_id
    )


def candidate_crashed(record: dict, config: Config) -> bool:
    return (
        len(record["pods"]) == 1
        and not record["pods"][0]["deleting"]
        and record["pods"][0]["attempt"] == record["attempt"]
        and any(
            c["image_id"] == config.image_id and c["exit_code"] not in (None, 0) and not c["ready"]
            for c in record["pods"][0]["containers"]
        )
    )
