"""Bounded KEDA pilot on the owned Kind cluster; no application changes."""

import argparse
import hashlib
import json
import math
import secrets
import sys
import time
import urllib.request
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_calibration as calibration
from scripts import scale_environment as env
from scripts import scale_observation as telemetry
from scripts.scale_contract import TARGET, utc, write

NAME = "core-worker-pilot"
OWNER = "fulfillflow-scale-pilot"
CONFIG = env.ROOT / "config/keda-pilot.json"


def query():
    return "SELECT count(*) FROM message_inbox WHERE type='tracking.apply.v1' AND state IN ('PENDING','RETRY_WAIT') AND next_attempt_at <= now() AND created_at <= now()-interval '5 seconds';"


def scaled_object(pin):
    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": NAME,
            "namespace": "fulfillflow",
            "labels": {"fulfillflow.io/owner": OWNER},
        },
        "spec": {
            "scaleTargetRef": {"name": TARGET},
            "minReplicaCount": 1,
            "maxReplicaCount": 2,
            "pollingInterval": pin["polling_seconds"],
            "advanced": {
                "horizontalPodAutoscalerConfig": {
                    "name": NAME,
                    "behavior": {
                        "scaleUp": {
                            "stabilizationWindowSeconds": pin["scale_up_stabilization_seconds"],
                            "policies": [{"type": "Pods", "value": 1, "periodSeconds": 15}],
                        },
                        "scaleDown": {
                            "stabilizationWindowSeconds": pin["scale_down_stabilization_seconds"],
                            "policies": [{"type": "Pods", "value": 1, "periodSeconds": 60}],
                        },
                    },
                }
            },
            "triggers": [
                {
                    "type": "postgresql",
                    "metricType": "AverageValue",
                    "metadata": {
                        "host": "postgres.fulfillflow.svc.cluster.local",
                        "port": "5432",
                        "dbName": "fulfillflow_core",
                        "userName": "keda_scale_reader",
                        "sslmode": "disable",
                        "query": query(),
                        "targetQueryValue": "1",
                    },
                    "authenticationRef": {"name": NAME},
                }
            ],
        },
    }


def k(private, args, namespace="fulfillflow", timeout=30, data=None):
    tool, _ = env.tools()
    return env.command(
        [
            tool,
            "--kubeconfig",
            private / "kubeconfig",
            "--context",
            "kind-" + calibration.CLUSTER,
            *(["-n", namespace] if namespace else []),
            *args,
        ],
        timeout=timeout,
        data=data,
    )


def get(private, kind, name, namespace="fulfillflow"):
    raw = k(private, ["get", kind, name, "--ignore-not-found", "-o", "json"], namespace)
    return json.loads(raw) if raw.strip() else None


def apply(private, item):
    return k(
        private,
        ["apply", "--server-side", "--field-manager=scale-pilot", "-f", "-"],
        data=json.dumps(item),
    )


def quantity(value):
    number = float(value[:-1]) / 1000 if value.endswith("m") else float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("INVALID_METRIC_VALUE")
    return number


class Pilot:
    def __init__(self, prepare_only=False):
        self.pin = json.loads(CONFIG.read_text())
        self.prepare_only = prepare_only
        self.logs = {}
        self.pods = {}
        self.log_gaps = []
        self.object_uid = None
        self.restart_baseline = {}
        self.metric_samples = []

    def install(self, private, output):
        namespace = get(private, "namespace", "keda")
        if (
            namespace
            and namespace["metadata"].get("labels", {}).get("fulfillflow.io/owner") != OWNER
        ):
            raise RuntimeError("FOREIGN_KEDA_NAMESPACE")
        if not namespace and get(private, "apiservice", "v1beta1.external.metrics.k8s.io"):
            raise RuntimeError("EXISTING_EXTERNAL_METRICS_PROVIDER")
        path = env.ROOT / ".tools/keda/keda-2.20.2-core.yaml"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            with urllib.request.urlopen(self.pin["manifest_url"], timeout=60) as response:
                path.write_bytes(response.read(8_000_000))
        if hashlib.sha256(path.read_bytes()).hexdigest() != self.pin["manifest_sha256"]:
            raise RuntimeError("KEDA_MANIFEST_HASH")
        items = list(yaml.safe_load_all(path.read_text(encoding="utf-8")))
        for item in items:
            if item["kind"] == "Namespace":
                item["metadata"].setdefault("labels", {})["fulfillflow.io/owner"] = OWNER
            if item["kind"] == "Deployment":
                for container in item["spec"]["template"]["spec"]["containers"]:
                    container["image"] = self.pin["images"][item["metadata"]["name"]]
                    for variable in container["env"]:
                        if variable["name"] == "WATCH_NAMESPACE":
                            variable["value"] = "fulfillflow"
        rendered = yaml.safe_dump_all(items)
        (output / "keda-install.yaml").write_text(rendered, encoding="utf-8")
        k(
            private,
            ["apply", "--server-side", "--field-manager=scale-pilot", "-f", "-"],
            namespace=None,
            timeout=120,
            data=rendered,
        )
        for name in self.pin["images"]:
            k(private, ["rollout", "status", "deployment/" + name, "--timeout=240s"], "keda", 250)
        k(
            private,
            [
                "wait",
                "--for=condition=Available",
                "apiservice/v1beta1.external.metrics.k8s.io",
                "--timeout=90s",
            ],
            timeout=100,
        )
        credential = private / "keda-reader.json"
        exists = (
            k(
                private,
                [
                    "exec",
                    "postgres-0",
                    "--",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "fulfillflow_core",
                    "-Atc",
                    "SELECT count(*) FROM pg_roles WHERE rolname='keda_scale_reader'",
                ],
            ).strip()
            == "1"
        )
        if exists != credential.exists():
            raise RuntimeError("KEDA_READER_IDENTITY_MISMATCH")
        if not exists:
            password = secrets.token_hex(32)
            write(credential, {"password": password})
            sql = f"CREATE ROLE keda_scale_reader LOGIN CONNECTION LIMIT 2 PASSWORD '{password}';\nGRANT CONNECT ON DATABASE fulfillflow_core TO keda_scale_reader;\nGRANT USAGE ON SCHEMA public TO keda_scale_reader;\nGRANT SELECT (state,next_attempt_at,created_at,type) ON message_inbox TO keda_scale_reader;\nALTER ROLE keda_scale_reader SET default_transaction_read_only=on;\nALTER ROLE keda_scale_reader SET statement_timeout='2000ms';\n"
            k(
                private,
                [
                    "exec",
                    "-i",
                    "postgres-0",
                    "--",
                    "psql",
                    "-U",
                    "postgres",
                    "-d",
                    "fulfillflow_core",
                    "-v",
                    "ON_ERROR_STOP=1",
                ],
                data=sql,
            )
        password = json.loads(credential.read_text())["password"]
        apply(
            private,
            {
                "apiVersion": "v1",
                "kind": "Secret",
                "metadata": {"name": NAME, "namespace": "fulfillflow"},
                "stringData": {"password": password},
            },
        )
        apply(
            private,
            {
                "apiVersion": "keda.sh/v1alpha1",
                "kind": "TriggerAuthentication",
                "metadata": {"name": NAME, "namespace": "fulfillflow"},
                "spec": {
                    "secretTargetRef": [{"parameter": "password", "name": NAME, "key": "password"}]
                },
            },
        )
        apply(
            private,
            {
                "apiVersion": "networking.k8s.io/v1",
                "kind": "NetworkPolicy",
                "metadata": {"name": "postgres-keda-pilot", "namespace": "fulfillflow"},
                "spec": {
                    "podSelector": {"matchLabels": {"app.kubernetes.io/name": "postgres"}},
                    "policyTypes": ["Ingress"],
                    "ingress": [
                        {
                            "from": [
                                {
                                    "namespaceSelector": {
                                        "matchLabels": {"kubernetes.io/metadata.name": "keda"}
                                    }
                                }
                            ],
                            "ports": [{"protocol": "TCP", "port": 5432}],
                        }
                    ],
                },
            },
        )
        write(
            output / "keda-identities.json",
            {
                "pin": self.pin,
                "deployments": [get(private, "deployment", n, "keda") for n in self.pin["images"]],
            },
        )

    def activate(self, private):
        if (
            get(private, "scaledobject", NAME)
            or json.loads(k(private, ["get", "hpa", "-o", "json"]))["items"]
        ):
            raise RuntimeError("EXISTING_SCALE_CONTROLLER")
        apply(private, scaled_object(self.pin))
        obj = get(private, "scaledobject", NAME)
        self.object_uid = obj["metadata"]["uid"]

    def status(self, private):
        obj = get(private, "scaledobject", NAME)
        hpa = get(private, "hpa", NAME)
        if not obj or obj["metadata"]["uid"] != self.object_uid:
            raise RuntimeError("SCALEDOBJECT_IDENTITY")
        result = {
            "utc": utc(),
            "monotonic": time.monotonic(),
            "scaledobject_status": obj.get("status", {}),
            "hpa_status": hpa.get("status", {}) if hpa else None,
            "hpa_spec": hpa.get("spec", {}) if hpa else None,
        }
        names = obj.get("status", {}).get("externalMetricNames", [])
        try:
            if len(names) != 1:
                raise RuntimeError("METRIC_NAME_NOT_READY")
            raw = json.loads(
                k(
                    private,
                    [
                        "get",
                        "--raw",
                        "/apis/external.metrics.k8s.io/v1beta1/namespaces/fulfillflow/"
                        + names[0]
                        + "?labelSelector=scaledobject.keda.sh%2Fname%3D"
                        + NAME,
                        "--request-timeout=5s",
                    ],
                    timeout=8,
                )
            )
            metrics = raw["items"]
            if len(metrics) != 1:
                raise RuntimeError("METRIC_RESPONSE_COUNT")
            result["metric"] = {
                "available": True,
                "value": quantity(metrics[0]["value"]),
                "timestamp": metrics[0]["timestamp"],
            }
        except (RuntimeError, KeyError, ValueError):
            result["metric"] = {"available": False}
        return result

    def wait_metric(self, private, available):
        deadline = time.monotonic() + 90
        records = []
        while time.monotonic() < deadline:
            result = self.status(private)
            records.append(result)
            if result["metric"]["available"] == available:
                return records
            time.sleep(5)
        raise RuntimeError("METRIC_STATE_TIMEOUT")

    def metric_probe(self, private, output):
        self.activate(private)
        records = self.wait_metric(private, True)
        faulty = scaled_object(self.pin)
        faulty["spec"]["triggers"][0]["metadata"]["query"] = "SELECT 1/0"
        write(output / "metric-healthy-before.json", records)
        try:
            apply(private, faulty)
            time.sleep(10)
            for _ in range(3):
                records.extend(self.wait_metric(private, False))
                time.sleep(5)
        finally:
            apply(private, scaled_object(self.pin))
        records.extend(self.wait_metric(private, True))
        write(
            output / "metric-fault-probe.json",
            {
                "records": records,
                "injected": "SQL division by zero in scaler query only",
                "restored": True,
            },
        )
        self.cleanup(private)

    def begin_load(self, private, folder):
        self.private = private
        self.since = utc()
        self.restart_baseline = {p["uid"]: p["restarts"] for p in telemetry.worker_pods(private)}
        self.activate(private)
        self.wait_metric(private, True)
        write(folder / "policy.json", scaled_object(self.pin))

    def sample(self, private, sample):
        sample.pop("replicas_fixed", None)
        sample["condition"] = "adaptive"
        sample["controller"] = self.status(private)
        self.metric_samples.append(sample["controller"])
        current = telemetry.worker_pods(private)
        for pod in current:
            self.pods[pod["uid"]] = pod
            try:
                raw = k(private, ["logs", pod["name"], "--since-time=" + self.since], timeout=10)
                for line in raw.splitlines():
                    try:
                        value = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(value, dict) and value.get("request_id"):
                        selected = telemetry.matching_records(line, {value["request_id"]})
                        for record in selected:
                            key = (pod["uid"], record["message_id"], record["timestamp"])
                            self.logs[key] = {**record, "pod": pod["name"], "pod_uid": pod["uid"]}
            except RuntimeError:
                self.log_gaps.append({"pod_uid": pod["uid"], "utc": utc()})
        sample["collection_end_monotonic"] = time.monotonic()
        return sample

    def attribution(self, private, admissions, path):
        self.sample(private, {})
        ids = {r["request_id"] for r in admissions.values() if r.get("request_id")}
        rows = [r for r in self.logs.values() if r["request_id"] in ids]
        complete = len(ids) == len(admissions) and all(
            sum(r["request_id"] == x for r in rows) == 1 for x in ids
        )
        complete = complete and all(
            p["restarts"] == self.restart_baseline.get(uid, 0) for uid, p in self.pods.items()
        )
        result = {
            "complete": complete,
            "records": rows,
            "pods": list(self.pods.values()),
            "log_gaps": self.log_gaps,
            "restart_baseline": self.restart_baseline,
            "per_pod": {
                p["name"]: sum(r["pod_uid"] == uid for r in rows) for uid, p in self.pods.items()
            },
        }
        write(path, result)
        return result

    def run(self, private, output, settings, values, base, expected, deadline):
        self.install(private, output)
        self.metric_probe(private, output)
        if self.prepare_only:
            write(output / "pilot-result.json", {"prepared": True, "load_executed": False})
            return
        ok = calibration.run_one(
            private, output / "adaptive", 1, settings, values, base, expected, deadline, policy=self
        )
        if not ok:
            raise RuntimeError("ADAPTIVE_FUNCTIONAL_OR_ATTRIBUTION_INCOMPLETE")
        idle = []
        until = time.monotonic() + self.pin["post_load_observation_seconds"]
        while time.monotonic() < until:
            idle.append(self.status(private))
            time.sleep(5)
        write(output / "post-load.json", idle)
        observed = self.metric_samples + idle
        unavailable = sum(not r["metric"]["available"] for r in observed)
        write(
            output / "metric-availability.json",
            {"samples": len(observed), "unavailable": unavailable},
        )
        if unavailable:
            raise RuntimeError("PILOT_METRIC_OBSERVATION_INCOMPLETE")
        write(
            output / "pilot-result.json",
            {
                "complete": True,
                "load_executed": True,
                "autoscaling_tested": True,
                "interpretation": "inspect sampled criterion, metric availability and HPA decisions; scaling not required",
            },
        )

    def cleanup(self, private):
        obj = get(private, "scaledobject", NAME)
        if obj:
            if (
                obj["metadata"].get("labels", {}).get("fulfillflow.io/owner") != OWNER
                or obj["metadata"]["uid"] != self.object_uid
            ):
                raise RuntimeError("CLEANUP_CONTROLLER_IDENTITY")
            k(
                private,
                [
                    "delete",
                    "scaledobject",
                    NAME,
                    "--cascade=foreground",
                    "--wait=true",
                    "--timeout=60s",
                ],
                timeout=70,
            )
        if get(private, "hpa", NAME):
            raise RuntimeError("HPA_STILL_PRESENT")
        controllers = json.loads(k(private, ["get", "hpa", "-o", "json"]))["items"]
        if any(h["spec"]["scaleTargetRef"]["name"] == TARGET for h in controllers):
            raise RuntimeError("FOREIGN_TARGET_HPA")
        k(private, ["scale", "deployment/" + TARGET, "--replicas=1"])
        telemetry.wait_worker_count(private, 1)
        self.object_uid = None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    private, output = args.private.resolve(), args.output.resolve()
    if private.is_relative_to(output) or output.is_relative_to(private):
        raise RuntimeError("PRIVATE_OUTPUT_OVERLAP")
    try:
        with calibration.exclusive(private):
            calibration._execute(private, output, extension=Pilot(args.prepare_only))
        print(
            json.dumps(
                {"complete": True, "output": str(output), "load_executed": not args.prepare_only}
            )
        )
    except Exception as error:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": type(error).__name__,
                    "code": str(error) if isinstance(error, RuntimeError) else "PILOT_FAILED",
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
