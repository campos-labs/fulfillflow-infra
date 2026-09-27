"""One read-only HTTP diagnostic in cloned APIs; no business writes or historical rollout."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import psutil

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import scale_environment as env
from scripts.http_trace_contract import (
    HTTP_HEALTH_PATHS,
    LABEL,
    ci_verdict,
    clone_api,
    peer_health_ready,
    verify_trace,
)
from scripts.scale_contract import CLUSTER, utc, write

ROOT = Path(__file__).resolve().parents[1]


def host_snapshot(minimum):
    battery = psutil.sensors_battery()
    return {
        "utc": utc(),
        "available_gib": psutil.virtual_memory().available / 1024**3,
        "required_gib": minimum,
        "power_plugged": battery.power_plugged if battery else None,
    }


def validate_host(snapshot):
    if snapshot["power_plugged"] is False:
        raise RuntimeError("HOST_ON_BATTERY")
    if snapshot["available_gib"] < snapshot["required_gib"]:
        raise RuntimeError("HOST_MEMORY_BELOW_GUARD")


class Runner:
    def __init__(self, private, output):
        self.private, self.output = private, output
        self.deadline = time.monotonic() + 600
        self.samples = []
        self.run_id = uuid4().hex
        self.stage = "preparation"
        self.query_started = False
        self.command_failures = []

    def check(self):
        sample = host_snapshot(2)
        self.samples.append(sample)
        validate_host(sample)
        if time.monotonic() >= self.deadline:
            raise RuntimeError("DIAGNOSTIC_DEADLINE")

    def command(self, args, *, data=None, timeout=90, allow_failure=False):
        self.check()
        process = subprocess.Popen(
            [env.executable(args[0]), *map(str, args[1:])],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        started = time.monotonic()
        try:
            initial = True
            while True:
                try:
                    stdout, stderr = process.communicate(data if initial else None, timeout=2)
                    break
                except subprocess.TimeoutExpired:
                    initial = False
                    self.check()
                    if time.monotonic() - started > timeout:
                        raise RuntimeError("COMMAND_DEADLINE")
            self.check()
            if process.returncode:
                self.command_failures.append(
                    {
                        "stage": self.stage,
                        "tool": Path(str(args[0])).stem,
                        "returncode": process.returncode,
                        "reason": "ROLLOUT_DEADLINE"
                        if "timed out waiting" in stderr
                        else "COMMAND_REJECTED",
                    }
                )
            if process.returncode and not allow_failure:
                raise RuntimeError("COMMAND_FAILED_" + Path(str(args[0])).stem.upper())
            return stdout
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

    def kube(self, args, data=None, timeout=90, allow_failure=False):
        tool, _ = env.tools()
        return self.command(
            [
                tool,
                "--kubeconfig",
                self.private / "kubeconfig",
                "--context",
                "kind-" + CLUSTER,
                "-n",
                "fulfillflow",
                *args,
            ],
            data=data,
            timeout=timeout,
            allow_failure=allow_failure,
        )

    def create(self, resource):
        resource["metadata"].setdefault("labels", {})["fulfillflow.io/http-run"] = self.run_id
        if resource["kind"] == "Deployment":
            resource["spec"]["template"]["metadata"].setdefault("labels", {})[
                "fulfillflow.io/http-run"
            ] = self.run_id
        return self.kube(["create", "-f", "-"], json.dumps(resource))


# No bodies, credentials or arbitrary endpoints are recorded by this pre-query probe.
HEALTH_PROBE = """
import json, sys, urllib.request, urllib.error
source, target = sys.argv[1:]
assert (source, target) in (("httpdiag-sink", "httpdiag-core"), ("httpdiag-core", "httpdiag-tracking"), ("httpdiag-tracking", "httpdiag-core"))
row = {"source": source, "target": target, "status": None, "error": None}
try:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://" + target + ":8000/health/ready", timeout=3) as response:
        row["status"] = response.status
except urllib.error.HTTPError as error:
    row["status"] = error.code
except urllib.error.URLError as error:
    row["error"] = type(error.reason).__name__
    row["errno"] = getattr(error.reason, "errno", None)
except Exception as error:
    row["error"] = type(error).__name__
print(json.dumps(row))
"""


def await_peer_health(runner):
    """Bounded preparation only; never retry the measured business query."""
    runner.stage = "peer_health"
    rounds = []
    for attempt in range(3):
        rows = []
        for source, target in HTTP_HEALTH_PATHS:
            row = json.loads(
                runner.kube(
                    [
                        "exec",
                        "deployment/" + source,
                        "--",
                        "python",
                        "-c",
                        HEALTH_PROBE,
                        source,
                        target,
                    ],
                    timeout=15,
                )
            )
            rows.append(row)
            # Preserve partial rounds if a later command fails.
            write(runner.output / f"peer-health-{attempt + 1}-{source}.json", row)
        rounds.append({"utc": utc(), "paths": rows})
        if peer_health_ready(rows):
            write(runner.output / "peer-health.json", {"rounds": rounds})
            return
        if attempt < 2:
            time.sleep(5)
    write(runner.output / "peer-health.json", {"rounds": rounds})
    raise RuntimeError("PEER_HEALTH_UNAVAILABLE")


def service(name, port):
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {"name": name, "labels": {LABEL: "true"}},
        "spec": {
            "selector": {"app.kubernetes.io/name": name},
            "ports": [{"port": port, "targetPort": port}],
        },
    }


def sink(image):
    labels = {"app.kubernetes.io/name": "httpdiag-sink", LABEL: "true"}
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {"name": "httpdiag-sink", "labels": {LABEL: "true"}},
        "spec": {
            "replicas": 1,
            "selector": {"matchLabels": labels},
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "fsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "sink",
                            "image": image,
                            "imagePullPolicy": "Never",
                            "command": ["python", "/diag/http_trace_receiver.py"],
                            "resources": {
                                "requests": {"cpu": "50m", "memory": "96Mi"},
                                "limits": {"cpu": "500m", "memory": "192Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "readinessProbe": {
                                "httpGet": {"path": "/snapshot", "port": 4318},
                                "periodSeconds": 2,
                            },
                            "volumeMounts": [
                                {"name": "scripts", "mountPath": "/diag", "readOnly": True}
                            ],
                        }
                    ],
                    "volumes": [{"name": "scripts", "configMap": {"name": "httpdiag-scripts"}}],
                },
            },
        },
    }


def network():
    peer = {"podSelector": {"matchLabels": {LABEL: "true"}}}
    ports = [{"protocol": "TCP", "port": p} for p in (8000, 4318)]
    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {"name": "httpdiag-peers", "labels": {LABEL: "true"}},
        "spec": {
            "podSelector": {"matchLabels": {LABEL: "true"}},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [{"from": [peer], "ports": ports}],
            "egress": [{"to": [peer], "ports": ports}],
        },
    }


def await_validation(config):
    gh = shutil.which("gh") or str(
        Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "GitHub CLI/gh.exe"
    )
    deadline = time.monotonic() + 1200
    print(
        "CI: checking the exact application reference before starting Kind (up to 20 minutes)",
        flush=True,
    )
    while True:
        record = json.loads(
            env.command(
                [
                    gh,
                    "run",
                    "view",
                    str(config["ci_run"]),
                    "--repo",
                    "campos-labs/fulfillflow",
                    "--json",
                    "status,conclusion,headSha,url",
                ],
                timeout=20,
            )
        )
        if ci_verdict(record, config["verification_sha"]):
            print("CI: approved; checking local memory and environment", flush=True)
            return record
        if time.monotonic() >= deadline:
            raise RuntimeError("CI_WAIT_DEADLINE")
        time.sleep(min(30, deadline - time.monotonic()))


def capture_query(runner, evidence, output, expected_spans=4):
    # Keep failed observer output too; it contains only the observer's allowlisted result.
    runner.stage = "functional_query"
    runner.query_started = True
    result = runner.kube(
        [
            "exec",
            "deployment/httpdiag-sink",
            "--",
            "python",
            "/diag/http_trace_observer.py",
            evidence["event_id"],
            evidence["checkpoint"]["inbox_event_id"],
            evidence["checkpoint"]["tracking_event_id"],
        ],
        timeout=30,
        allow_failure=True,
    )
    functional = json.loads(result)
    write(output / "functional.json", functional)
    if not functional.get("trace_id"):
        raise RuntimeError("OBSERVER_TRACE_NOT_CREATED")
    runner.stage = "trace_collection"
    snapshot = None
    for _ in range(10):
        snapshot = json.loads(
            runner.kube(
                [
                    "exec",
                    "deployment/httpdiag-sink",
                    "--",
                    "python",
                    "-c",
                    "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:4318/snapshot', timeout=2).read().decode())",
                ],
                timeout=10,
            )
        )
        if (
            len([r for r in snapshot["records"] if r["trace_id"] == functional["trace_id"]])
            >= expected_spans
        ):
            break
        time.sleep(1)
    write(output / "trace-records.json", snapshot)
    return snapshot, functional


def execute(private, output, scenario="healthy"):
    if CLUSTER != "fulfillflow-observe-01":
        raise RuntimeError("WRONG_ENVIRONMENT")
    config = json.loads((ROOT / "config/http-observability.json").read_bytes())
    validation = await_validation(config)
    entry = host_snapshot(5)
    try:
        validate_host(entry)
    except RuntimeError:
        print(json.dumps({"preflight": entry}))
        raise
    if env.command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    identity = json.loads((private / "identity.json").read_bytes())
    if identity.get("source") != "9e3a135a00db218643633c7165d3106f0c8285e1":
        raise RuntimeError("HISTORICAL_REFERENCE")
    node = json.loads(env.command(["docker", "inspect", identity["container_id"]]))[0]
    if node["Config"]["Labels"].get("io.x-k8s.kind.cluster") != CLUSTER or node["State"]["Running"]:
        raise RuntimeError("NODE_IDENTITY")
    image = json.loads(env.command(["docker", "image", "inspect", config["image"]]))[0]
    if (
        image["Id"] != config["image_id"]
        or image["Config"].get("Labels", {}).get("org.opencontainers.image.revision")
        != config["application_sha"]
    ):
        raise RuntimeError("DIAGNOSTIC_IMAGE_IDENTITY")
    output.mkdir(parents=True, exist_ok=False)
    runner = Runner(private, output)
    evidence = json.loads(
        (ROOT / "docs/evidence/observability/records/healthy-01/functional.json").read_bytes()
    )
    write(
        output / "protocol.json",
        {
            "utc": utc(),
            "run_id": runner.run_id,
            "entry": entry,
            "runtime": config,
            "application_ci": validation,
            "infrastructure_sha": env.command(["git", "-C", ROOT, "rev-parse", "HEAD"]).strip(),
            "namespace_uid": identity["namespace_uid"],
            "query_count": 3 if scenario == "transport-fault" else 1,
            "scenario": scenario,
            "preparation_health_checks": {
                "paths": 3,
                "maximum_rounds": 3,
                "business_query_retries": 0,
            },
            "business_writes": 0,
            "deadline_seconds": 600,
            "event_id": evidence["event_id"],
            "scripts": {
                name: hashlib.sha256((ROOT / "scripts" / name).read_bytes()).hexdigest()
                for name in (
                    "http_trace_fault.py",
                    "http_trace_pilot.py",
                    "http_trace_contract.py",
                    "http_trace_receiver.py",
                    "http_trace_observer.py",
                )
            },
        },
    )
    complete, error, stopped = False, None, False
    created = []
    originals = {}
    try:
        print("HTTP tracing: starting dedicated node, historical deployments unchanged", flush=True)
        runner.stage = "kubernetes_startup"
        runner.command(["docker", "start", identity["container_id"]])
        for _ in range(30):
            try:
                ns = json.loads(
                    runner.kube(["get", "namespace", "fulfillflow", "-o", "json"], timeout=10)
                )
                break
            except RuntimeError as failure:
                if str(failure) not in ("COMMAND_FAILED_KUBECTL", "COMMAND_DEADLINE"):
                    raise
                time.sleep(2)
        else:
            raise RuntimeError("KUBERNETES_STARTUP")
        if ns["metadata"]["uid"] != identity["namespace_uid"]:
            raise RuntimeError("NAMESPACE_IDENTITY")
        if json.loads(
            runner.kube(
                [
                    "get",
                    "deployment,service,configmap,networkpolicy",
                    "-l",
                    LABEL + "=true",
                    "-o",
                    "json",
                ]
            )
        )["items"]:
            raise RuntimeError("DIAGNOSTIC_RESOURCES_ALREADY_EXIST")
        runner.stage = "image_load"
        _, kind = env.tools()
        runner.command(
            [kind, "load", "docker-image", config["image"], "--name", CLUSTER], timeout=180
        )
        runner.stage = "create_diagnostic_resources"
        runner.create(
            {
                "apiVersion": "v1",
                "kind": "ConfigMap",
                "metadata": {"name": "httpdiag-scripts", "labels": {LABEL: "true"}},
                "data": {
                    name: (ROOT / "scripts" / name).read_text(encoding="utf-8")
                    for name in (
                        "http_trace_receiver.py",
                        "http_trace_observer.py",
                        "http_trace_contract.py",
                    )
                },
            }
        )
        runner.create(network())
        runner.create(sink(config["image"]))
        created.append("httpdiag-sink")
        runner.create(service("httpdiag-sink", 4318))
        for role in ("tracking", "core"):
            source = json.loads(runner.kube(["get", "deployment", role, "-o", "json"]))
            originals[role] = source["spec"]
            runner.create(clone_api(source, role, config["image"]))
            created.append("httpdiag-" + role)
            runner.create(service("httpdiag-" + role, 8000))
        for name in created:
            runner.stage = "rollout_" + name
            runner.kube(["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130)
        runner.check()
        pods = json.loads(runner.kube(["get", "pods", "-l", LABEL + "=true", "-o", "json"]))[
            "items"
        ]
        write(
            output / "runtime.json",
            [
                {
                    "name": p["metadata"]["name"],
                    "uid": p["metadata"]["uid"],
                    "containers": [
                        {
                            "image_id": c.get("imageID"),
                            "ready": c.get("ready"),
                            "restarts": c.get("restartCount"),
                        }
                        for c in p["status"].get("containerStatuses", [])
                    ],
                }
                for p in pods
            ],
        )
        print("HTTP tracing: checking peer readiness paths before the diagnostic", flush=True)
        await_peer_health(runner)
        print("HTTP tracing: bounded GET sequence, no webhook, then export collection", flush=True)
        if scenario == "transport-fault":
            from scripts.http_trace_fault import run_sequence

            run_sequence(runner, evidence, capture_query)
        else:
            snapshot, functional = capture_query(runner, evidence, output)
            write(output / "review.json", verify_trace(snapshot, functional))
        try:
            metrics = json.loads(
                runner.kube(
                    ["get", "--raw", "/apis/metrics.k8s.io/v1beta1/namespaces/fulfillflow/pods"],
                    timeout=10,
                )
            )
            names = {p["metadata"]["name"] for p in pods}
            usage = [
                {
                    "name": p["metadata"]["name"],
                    "timestamp": p.get("timestamp"),
                    "window": p.get("window"),
                    "containers": [
                        {"name": c["name"], "usage": c.get("usage")}
                        for c in p.get("containers", [])
                    ],
                }
                for p in metrics["items"]
                if p["metadata"]["name"] in names
            ]
            write(
                output / "resources.json",
                {
                    "available": len(usage) == len(names),
                    "pods": usage,
                    "causal_overhead_measured": False,
                },
            )
        except RuntimeError as failure:
            if str(failure) != "COMMAND_FAILED_KUBECTL":
                raise
            write(
                output / "resources.json",
                {
                    "available": False,
                    "reason": "METRICS_API_UNAVAILABLE",
                    "causal_overhead_measured": False,
                },
            )
        complete = True
    except Exception as failure:
        frames = []
        tb = failure.__traceback__
        while tb is not None:
            frames.append(
                {
                    "file": Path(tb.tb_frame.f_code.co_filename).name,
                    "function": tb.tb_frame.f_code.co_name,
                    "line": tb.tb_lineno,
                }
            )
            tb = tb.tb_next
        write(output / "failure-location.json", {"type": type(failure).__name__, "frames": frames})
        error = (
            str(failure)
            if isinstance(failure, (RuntimeError, ValueError))
            else type(failure).__name__
        )
    finally:
        if error:
            try:
                statuses = json.loads(
                    env.kubectl(
                        private, ["get", "pods", "-l", LABEL + "=true", "-o", "json"], timeout=15
                    )
                )["items"]
                write(
                    output / "failure-pods.json",
                    [
                        {
                            "name": p["metadata"]["name"],
                            "phase": p.get("status", {}).get("phase"),
                            "containers": [
                                {
                                    "ready": c.get("ready"),
                                    "restart_count": c.get("restartCount"),
                                    "states": {
                                        k: {
                                            key: value
                                            for key, value in v.items()
                                            if key
                                            in ("reason", "exitCode", "startedAt", "finishedAt")
                                        }
                                        for k, v in c.get("state", {}).items()
                                    },
                                }
                                for c in p.get("status", {}).get("containerStatuses", [])
                            ],
                        }
                        for p in statuses
                    ],
                )
            except Exception:
                write(output / "failure-pods.json", {"available": False})
        # Cleanup bypasses measurement guards but targets only resources created in this run.
        try:
            owned = json.loads(
                env.kubectl(
                    private,
                    [
                        "get",
                        "deployments",
                        "-l",
                        "fulfillflow.io/http-run=" + runner.run_id,
                        "-o",
                        "json",
                    ],
                    timeout=20,
                )
            )["items"]
            for deployment in owned:
                name = deployment["metadata"]["name"]
                if name not in ("httpdiag-core", "httpdiag-tracking", "httpdiag-sink"):
                    raise RuntimeError("CLEANUP_RESOURCE_IDENTITY")
                env.kubectl(private, ["scale", "deployment/" + name, "--replicas=0"], timeout=20)
            unchanged = all(
                json.loads(
                    env.kubectl(private, ["get", "deployment", name, "-o", "json"], timeout=20)
                )["spec"]
                == spec
                for name, spec in originals.items()
            )
            write(
                output / "preservation.json",
                {
                    "historical_deployment_specs_unchanged": unchanged,
                    "historical_deployments_checked": sorted(originals),
                    "diagnostic_replicas_requested": 0,
                },
            )
            if not unchanged:
                complete, error = False, "HISTORICAL_SPEC_CHANGED"
        except Exception:
            complete, error = False, error or "RESOURCE_CLEANUP_UNCONFIRMED"
        try:
            env.command(["docker", "stop", "--timeout", "30", identity["container_id"]], timeout=60)
            stopped = not json.loads(
                env.command(["docker", "inspect", identity["container_id"]], timeout=10)
            )[0]["State"]["Running"]
        except Exception:
            pass
        if not stopped:
            complete, error = False, error or "SHUTDOWN_UNCONFIRMED"
        write(output / "host.json", runner.samples)
        write(output / "command-failures.json", runner.command_failures)
        write(
            output / "summary.json",
            {
                "complete": complete,
                "error": error,
                "container_stopped": stopped,
                "business_writes": 0,
                "last_stage": runner.stage,
                "query_started": runner.query_started,
            },
        )
    print(
        json.dumps(
            {
                "complete": complete,
                "error": error,
                "container_stopped": stopped,
                "output": str(output),
            }
        )
    )
    return 0 if complete else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scenario", choices=("healthy", "transport-fault"), default="healthy")
    args = parser.parse_args()
    lock = ROOT / "artifacts/observability-pilot.lock"
    owned = False
    try:
        with lock.open("x"):
            owned = True
        raise SystemExit(execute(args.private.resolve(), args.output.resolve(), args.scenario))
    except Exception as error:
        print(
            json.dumps(
                {
                    "complete": False,
                    "error": str(error)
                    if isinstance(error, RuntimeError)
                    else type(error).__name__,
                }
            )
        )
        raise SystemExit(1) from None
    finally:
        if owned:
            lock.unlink()
