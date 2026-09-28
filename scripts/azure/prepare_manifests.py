"""Materialize AKS manifests offline from the guarded candidate; never apply them."""

import argparse
import copy
import hashlib
import ipaddress
import json
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PHASES = ("foundations", "migrations", "runtime")


def check_images(images: dict, registry: str) -> None:
    if not re.fullmatch(r"[a-z0-9]{5,50}\.azurecr\.io", registry):
        raise ValueError("INVALID_REGISTRY")
    if not images:
        raise ValueError("IMAGE_MAP_EMPTY")
    for source, target in images.items():
        if not isinstance(source, str) or not isinstance(target, str):
            raise ValueError("INVALID_IMAGE_MAP")
        if not re.fullmatch(re.escape(registry) + r"/[a-z0-9/._-]+@sha256:[0-9a-f]{64}", target):
            raise ValueError("ACR_DIGEST_REQUIRED")
        if target.endswith("0" * 64):
            raise ValueError("PLACEHOLDER_DIGEST")


def materialize(documents: list[dict], images: dict, window: str, registry: str) -> list[dict]:
    check_images(images, registry)
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", window):
        raise ValueError("INVALID_WINDOW_ID")
    result = copy.deepcopy(documents)
    workloads = {"Deployment", "StatefulSet", "Job"}
    for document in result:
        if document["kind"] == "Secret":
            raise ValueError("SECRET_IN_RENDER")
        metadata = document["metadata"]
        if metadata.get("namespace", "fulfillflow") != "fulfillflow":
            raise ValueError("UNEXPECTED_NAMESPACE")
        if document["kind"] == "Namespace" and metadata["name"] != "fulfillflow":
            raise ValueError("UNEXPECTED_NAMESPACE")
        metadatas = [metadata]
        if document["kind"] in workloads:
            template = document["spec"]["template"]
            metadatas.append(template["metadata"])
            pod = template["spec"]
            selector = pod.get("nodeSelector")
            if selector != {"fulfillflow.io/deployment-approved": "example-never-schedule"}:
                raise ValueError("CANDIDATE_GUARD_CHANGED")
            del pod["nodeSelector"]
            for container in pod.get("containers", []) + pod.get("initContainers", []):
                source = container["image"]
                if source not in images:
                    raise ValueError("UNMAPPED_IMAGE")
                container["image"] = images[source]
                container["imagePullPolicy"] = "IfNotPresent"
        for item in metadatas:
            annotations = item.get("annotations", {})
            if annotations.get("fulfillflow.io/validation-only") != "true":
                raise ValueError("CANDIDATE_ANNOTATION_MISSING")
            annotations.pop("fulfillflow.io/validation-only")
            if (
                annotations.pop("fulfillflow.io/deployment-blocked", None)
                != "environment-and-image-provenance-not-approved"
            ):
                raise ValueError("CANDIDATE_ANNOTATION_CHANGED")
            annotations["fulfillflow.io/environment"] = "aks-portability"
            item.setdefault("labels", {})["fulfillflow.io/window"] = window
    return result


def network_probe(image: str, registry: str, window: str, address: str, allowed: bool) -> dict:
    check_images({"probe": image}, registry)
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,39}", window):
        raise ValueError("INVALID_WINDOW_ID")
    ip = ipaddress.ip_address(address)
    if ip.version != 4 or not ip.is_private or ip.is_loopback or ip.is_unspecified:
        raise ValueError("PRIVATE_POSTGRES_POD_IP_REQUIRED")
    name = "aks-network-allowed" if allowed else "aks-network-denied"
    labels = {"fulfillflow.io/window": window}
    if allowed:
        labels["fulfillflow.io/database-client"] = "true"
    # A blocked connection alone does not prove enforcement: pair with allowed success.
    program = (
        "import socket,json,sys,errno\n"
        "s=socket.socket(); s.settimeout(5)\n"
        f"r=s.connect_ex(({str(ip)!r},5432)); s.close()\n"
        "print(json.dumps({'connected':r==0,'errno':r}))\n"
        + (
            "sys.exit(0 if r==0 else 1)\n"
            if allowed
            else "sys.exit(0 if r in (errno.ETIMEDOUT,errno.EAGAIN) else 1)\n"
        )
    )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": "fulfillflow", "labels": labels},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 45,
            "template": {
                "metadata": {"labels": labels},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "probe",
                            "image": image,
                            "command": ["python", "-c", program],
                            "resources": {
                                "requests": {"cpu": "25m", "memory": "32Mi"},
                                "limits": {"cpu": "100m", "memory": "64Mi"},
                            },
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                        }
                    ],
                },
            },
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--images", required=True, type=Path, help="Private source-to-ACR digest JSON"
    )
    parser.add_argument("--registry", required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--kubectl", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--postgres-pod-ip")
    parser.add_argument("--probe-image")
    args = parser.parse_args()
    try:
        images = json.loads(args.images.read_bytes())
        rendered = {}
        for phase in PHASES:
            response = subprocess.run(
                [
                    str(args.kubectl.resolve()),
                    "kustomize",
                    str(ROOT / "k8s/overlays/aks-portability" / phase),
                ],
                check=True,
                capture_output=True,
                timeout=60,
            )
            documents = list(yaml.safe_load_all(response.stdout))
            rendered[phase] = yaml.safe_dump_all(
                materialize(documents, images, args.window, args.registry), sort_keys=False
            ).encode()
        if bool(args.postgres_pod_ip) != bool(args.probe_image):
            raise ValueError("PROBE_REQUIRES_POD_IP_AND_IMAGE")
        if args.postgres_pod_ip:
            probes = [
                network_probe(
                    args.probe_image, args.registry, args.window, args.postgres_pod_ip, allowed
                )
                for allowed in (True, False)
            ]
            rendered["network-probes"] = yaml.safe_dump_all(probes, sort_keys=False).encode()
        args.output.mkdir(parents=True, exist_ok=False)
        hashes = {}
        for phase, data in rendered.items():
            (args.output / f"{phase}.yaml").write_bytes(data)
            hashes[phase] = hashlib.sha256(data).hexdigest()
        summary = {
            "materialized": True,
            "applied": False,
            "image_provenance_verified": False,
            "window": args.window,
            "sha256": hashes,
        }
        (args.output / "manifest.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, yaml.YAMLError):
        print(json.dumps({"materialized": False, "applied": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
