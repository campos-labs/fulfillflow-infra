"""Dedicated Kind bootstrap. Refuses existing cluster/output; preserves failures."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from k8s.prepare_rabbitmq_definitions import build_definitions
from scripts.scale_contract import CLUSTER, SOURCE, write

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "fulfillflow-kind-runtime:source-9e3a135a00db"
IMAGE_ID = "sha256:582a858debe2ff64d481e810b2d5ae5a1aba6a669516bca36a15eb12e77ec072"


def command(args, *, data=None, timeout=90):
    result = subprocess.run(
        [str(x) for x in args],
        input=data,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError("COMMAND_FAILED_" + Path(str(args[0])).stem.upper())
    return result.stdout


def tools():
    suffix = ".exe" if os.name == "nt" else ""
    return ROOT / ".tools/kubectl" / ("kubectl" + suffix), ROOT / ".tools/kind" / ("kind" + suffix)


def kubectl(private: Path, args, data=None, timeout=90):
    tool, _ = tools()
    return command(
        [
            tool,
            "--kubeconfig",
            private / "kubeconfig",
            "--context",
            "kind-" + CLUSTER,
            "-n",
            "fulfillflow",
            *args,
        ],
        data=data,
        timeout=timeout,
    )


def protect(path):
    path.mkdir(parents=True, exist_ok=False)
    if os.name == "nt":
        actor = command(["whoami"]).strip()
        command(["icacls", path, "/inheritance:r", "/grant:r", actor + ":(OI)(CI)F"])
    else:
        path.chmod(0o700)


def preflight():
    info = json.loads(command(["docker", "info", "--format", "{{json .}}"]))
    if info["OSType"] != "linux" or info["NCPU"] < 4 or info["MemTotal"] < 7 * 1024**3:
        raise RuntimeError("DOCKER_CAPACITY")
    if command(["docker", "ps", "-q"]).strip():
        raise RuntimeError("CONCURRENT_CONTAINERS")
    image = json.loads(command(["docker", "image", "inspect", IMAGE]))[0]
    if (
        image["Id"] != IMAGE_ID
        or image["Config"]["Labels"].get("org.opencontainers.image.revision") != SOURCE
    ):
        raise RuntimeError("IMAGE_IDENTITY")
    tool, kind = tools()
    pin = json.loads((ROOT / "config/kind-toolchain.json").read_text())
    if (
        os.name == "nt"
        and hashlib.sha256(kind.read_bytes()).hexdigest() != pin["windows_amd64_sha256"]
    ):
        raise RuntimeError("KIND_HASH")
    command([tool, "version", "--client", "-o", "json"])
    if CLUSTER in command([kind, "get", "clusters"]).split():
        raise RuntimeError("CLUSTER_EXISTS")
    return {
        "cpus": info["NCPU"],
        "memory_bytes": info["MemTotal"],
        "cgroup": info.get("CgroupVersion"),
        "application_sha": SOURCE,
        "image_id": IMAGE_ID,
    }


def bootstrap(private: Path, output: Path):
    if private.resolve().is_relative_to(ROOT) or private.exists() or output.exists():
        raise RuntimeError("EXCLUSIVE_PATHS_REQUIRED")
    facts = preflight()
    output.mkdir(parents=True, exist_ok=False)
    write(output / "preflight.json", facts)
    protect(private)
    _, kind = tools()
    config = yaml.safe_load((ROOT / "config/kind-local.yaml").read_text())
    config["name"] = CLUSTER
    write(output / "kind-config.json", config)
    created = False
    try:
        # --retain prevents Kind from deleting a failed cluster and its diagnostics.
        created = True
        command(
            [
                kind,
                "create",
                "cluster",
                "--name",
                CLUSTER,
                "--config",
                output / "kind-config.json",
                "--kubeconfig",
                private / "kubeconfig",
                "--retain",
                "--wait",
                "180s",
            ],
            timeout=300,
        )
        command(["docker", "update", "--restart=no", CLUSTER + "-control-plane"])
        command([kind, "load", "docker-image", IMAGE, "--name", CLUSTER], timeout=240)
        phases = {}
        tool, _ = tools()
        for phase in ("foundations", "migrations", "runtime"):
            rendered = command([tool, "kustomize", ROOT / "k8s/overlays/kind-local" / phase])
            phases[phase] = list(yaml.safe_load_all(rendered))
            (output / (phase + ".yaml")).write_text(rendered, encoding="utf-8")
        ns = next(x for x in phases["foundations"] if x["kind"] == "Namespace")
        kubectl(private, ["apply", "-f", "-"], json.dumps(ns))
        uid = json.loads(kubectl(private, ["get", "namespace", "fulfillflow", "-o", "json"]))[
            "metadata"
        ]["uid"]
        keys = (
            "postgres",
            "core",
            "tracking",
            "notifications",
            "internal",
            "session",
            "notification_api",
            "alpha",
            "beta",
            "amqp_core",
            "amqp_tracking",
            "amqp_notifications",
        )
        values = {key: secrets.token_hex(32) for key in keys}
        write(private / "values.json", values)

        def secret(name, items):
            kubectl(
                private,
                ["create", "-f", "-"],
                json.dumps(
                    {
                        "apiVersion": "v1",
                        "kind": "Secret",
                        "metadata": {"name": name, "namespace": "fulfillflow"},
                        "type": "Opaque",
                        "stringData": items,
                    }
                ),
            )

        secret(
            "postgres-bootstrap",
            {
                "POSTGRES_PASSWORD": values["postgres"],
                **{
                    owner.upper() + "_DB_PASSWORD": values[owner]
                    for owner in ("core", "tracking", "notifications")
                },
            },
        )
        for owner in ("core", "tracking", "notifications"):
            secret(
                owner + "-database",
                {
                    "DATABASE_URL": f"postgresql+psycopg://fulfillflow_{owner}:{values[owner]}@postgres:5432/fulfillflow_{owner}"
                },
            )
            secret(
                owner + "-amqp",
                {
                    "AMQP_URL": f"amqp://{owner}:{values['amqp_' + owner]}@rabbitmq:5672/fulfillflow-v13"
                },
            )
        secret(
            "core-runtime",
            {
                "INTERNAL_API_SECRET": values["internal"],
                "SESSION_SECRET": values["session"],
                "NOTIFICATIONS_API_SECRET": values["notification_api"],
            },
        )
        secret(
            "tracking-runtime",
            {
                "INTERNAL_API_SECRET": values["internal"],
                "CARRIER_ALPHA_WEBHOOK_SECRET": values["alpha"],
                "CARRIER_BETA_WEBHOOK_SECRET": values["beta"],
            },
        )
        secret("notifications-runtime", {"INTERNAL_API_SECRET": values["notification_api"]})
        definitions = build_definitions(
            {owner: values["amqp_" + owner] for owner in ("core", "tracking", "notifications")}
        )
        secret("rabbitmq-definitions", {"definitions.json": json.dumps(definitions)})
        kubectl(private, ["apply", "-f", "-"], yaml.safe_dump_all(phases["foundations"]))
        for name in ("postgres", "rabbitmq"):
            kubectl(
                private, ["rollout", "status", "statefulset/" + name, "--timeout=240s"], timeout=250
            )
        for job in phases["migrations"]:
            kubectl(private, ["create", "-f", "-"], json.dumps(job))
            kubectl(
                private,
                [
                    "wait",
                    "--for=condition=complete",
                    "job/" + job["metadata"]["name"],
                    "--timeout=180s",
                ],
                timeout=190,
            )
        kubectl(private, ["apply", "-f", "-"], yaml.safe_dump_all(phases["runtime"]))
        for name in (
            "core",
            "tracking",
            "notifications",
            "core-worker",
            "tracking-worker",
            "notifications-worker",
        ):
            kubectl(
                private, ["rollout", "status", "deployment/" + name, "--timeout=120s"], timeout=130
            )
        # Dedicated read-only role. Password is sent through stdin, never argv/logs.
        observer = secrets.token_hex(32)
        sql = (
            f"CREATE ROLE scale_observer LOGIN PASSWORD '{observer}';\n"
            "GRANT CONNECT ON DATABASE fulfillflow_core TO scale_observer;\n"
            "GRANT USAGE ON SCHEMA public TO scale_observer;\n"
            "GRANT SELECT (state,next_attempt_at,created_at,type) ON message_inbox TO scale_observer;\n"
            "ALTER ROLE scale_observer SET default_transaction_read_only=on;\n"
            "ALTER ROLE scale_observer SET statement_timeout='2000ms';\n"
        )
        kubectl(
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
            sql,
        )
        secret("scale-observer", {"password": observer})
        values["observer"] = observer
        # Exclusive replacement of our own freshly created private file only.
        (private / "values.json").write_text(json.dumps(values), encoding="utf-8")
        write(
            private / "identity.json",
            {
                "namespace_uid": uid,
                "image_id": IMAGE_ID,
                "source": SOURCE,
                "container_id": json.loads(
                    command(["docker", "inspect", CLUSTER + "-control-plane"])
                )[0]["Id"],
            },
        )
        write(output / "bootstrap.json", {"complete": True, "namespace_uid": uid, **facts})
    except Exception as error:
        write(
            output / "bootstrap-error.json",
            {
                "complete": False,
                "error": type(error).__name__,
                "code": str(error) if isinstance(error, RuntimeError) else "BOOTSTRAP_FAILED",
            },
        )
        raise
    finally:
        if created:
            # Cluster name is dedicated; never delete volumes or the historical cluster.
            command(["docker", "stop", "--timeout", "30", CLUSTER + "-control-plane"], timeout=60)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    try:
        if args.check:
            print(json.dumps(preflight()))
        else:
            bootstrap(args.private, args.output)
    except Exception as error:
        print(json.dumps({"complete": False, "error": type(error).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
