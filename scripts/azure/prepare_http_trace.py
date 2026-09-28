"""Prepare the optional healthy AKS tracing slice offline; never deploy or authorize it."""

import argparse
import json
import math
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.azure.prepare_manifests import check_images  # noqa: E402
from scripts.http_trace_contract import LABEL, clone_api  # noqa: E402
from scripts.http_trace_pilot import network, service, sink  # noqa: E402


def gate(record: dict) -> dict:
    checks = (
        "window_authorized",
        "healthy_extension_authorized",
        "basic_acceptance_complete",
        "evidence_preserved",
        "no_pending_issue",
        "cost_within_authorized_limit",
        "no_new_azure_resources_or_roles",
        "capacity_verified",
        "prepared_and_reviewed",
    )
    failed = [key for key in checks if record.get(key) is not True]
    elapsed = record.get("elapsed_seconds")
    if type(elapsed) not in (int, float) or not math.isfinite(elapsed) or not 0 <= elapsed <= 15300:
        failed.append("must_start_by_4h15")
    return {
        "eligible": not failed,
        "failed_conditions": failed,
        "scenario": "healthy",
        "maximum_extension_seconds": 2700,
        "cleanup_reserve_seconds": 3600,
        "fault_authorized": False,
        "monitor_authorized": False,
        "limit": "Evidence supplied by operator; eligibility is not a resource mutation or independent authorization.",
    }


def prepare(runtime: list[dict], image: str, registry: str, window: str) -> list[dict]:
    check_images({"diagnostic": image}, registry)
    sources = {}
    for role in ("core", "tracking"):
        matches = [
            d for d in runtime if d.get("kind") == "Deployment" and d["metadata"]["name"] == role
        ]
        if len(matches) != 1:
            raise ValueError("SOURCE_MISSING_OR_DUPLICATE")
        source = matches[0]
        if (
            source["metadata"].get("namespace") != "fulfillflow"
            or source["metadata"].get("labels", {}).get("fulfillflow.io/window") != window
        ):
            raise ValueError("SOURCE_WINDOW_MISMATCH")
        if (
            source["spec"]["template"]["spec"]
            .get("nodeSelector", {})
            .get("fulfillflow.io/deployment-approved")
        ):
            raise ValueError("UNMATERIALIZED_SOURCE")
        sources[role] = source
    result = [
        {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": "httpdiag-scripts"},
            "data": {
                name: (ROOT / "scripts" / name).read_text(encoding="utf-8")
                for name in (
                    "http_trace_receiver.py",
                    "http_trace_observer.py",
                    "http_trace_contract.py",
                )
            },
        },
        network(),
        sink(image),
        service("httpdiag-sink", 4318),
    ]
    for role in ("core", "tracking"):
        result.extend([clone_api(sources[role], role, image), service("httpdiag-" + role, 8000)])
    for item in result:
        item["metadata"]["namespace"] = "fulfillflow"
        item["metadata"].setdefault("labels", {}).update(
            {LABEL: "true", "fulfillflow.io/window": window}
        )
        if item["kind"] == "Deployment":
            item["spec"]["template"]["metadata"]["labels"]["fulfillflow.io/window"] = window
            for container in item["spec"]["template"]["spec"]["containers"]:
                container["imagePullPolicy"] = "IfNotPresent"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", required=True, type=Path)
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--image", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--window", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        verdict = gate(json.loads(args.gate.read_bytes()))
        # Preparation is permitted with a closed gate; deployment is always separate.
        documents = prepare(
            list(yaml.safe_load_all(args.runtime.read_text(encoding="utf-8"))),
            args.image,
            args.registry,
            args.window,
        )
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "healthy.yaml").write_text(
            yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8"
        )
        (args.output / "gate-review.json").write_text(
            json.dumps(verdict, indent=2), encoding="utf-8"
        )
        print(json.dumps({"prepared": True, "applied": False, "gate": verdict}))
        return 0
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        print(json.dumps({"prepared": False, "applied": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
