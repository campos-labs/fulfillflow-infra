"""Read-only AKS persistence capture through an explicit context and owned HTTP tunnel.

No resource mutation, retries, secret reads or ambient kubeconfig. Outputs are private;
selected projections preserve queried IDs/states, not full business payloads.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from verify_flow import Failure, HttpTransport  # noqa: E402


def require(value: bool) -> None:
    if not value:
        raise ValueError("CAPTURE_CONTRACT_FAILED")


def validate_target(target: dict) -> None:
    require(bool(re.fullmatch(r"[a-z][a-z0-9-]{2,39}", target["window"])))
    require(bool(re.fullmatch(r"https://[a-zA-Z0-9.-]+(?::443)?", target["api_server"])))
    require(
        bool(
            re.fullmatch(
                r"/subscriptions/[0-9a-fA-F-]{36}/resourceGroups/[^/]+/providers/Microsoft.ContainerService/managedClusters/[^/]+",
                target["cluster_id"],
            )
        )
    )
    for key in ("system_namespace_uid", "order_id", "shipment_id", "event_id", "notification_id"):
        require(str(UUID(target[key])) == target[key])


def infrastructure(target: dict, kube) -> dict:
    """Verify context identity and PVC/PV binding, then select safe provenance fields."""
    validate_target(target)
    config = kube(["config", "view", "--minify", "-o", "json"])
    require(len(config["clusters"]) == 1)
    require(config["clusters"][0]["cluster"]["server"] == target["api_server"])
    system = kube(["get", "namespace", "kube-system", "-o", "json"])
    require(system["metadata"]["uid"] == target["system_namespace_uid"])
    pod = kube(["get", "pod", "postgres-0", "-n", "fulfillflow", "-o", "json"])
    require(pod["metadata"]["labels"].get("fulfillflow.io/window") == target["window"])
    require(not pod["metadata"].get("deletionTimestamp"))
    require(
        any(
            c["type"] == "Ready" and c["status"] == "True"
            for c in pod["status"].get("conditions", [])
        )
    )
    owners = pod["metadata"].get("ownerReferences", [])
    require(
        any(
            o["kind"] == "StatefulSet" and o["name"] == "postgres" and o.get("controller") is True
            for o in owners
        )
    )
    claims = [
        v["persistentVolumeClaim"]["claimName"]
        for v in pod["spec"]["volumes"]
        if "persistentVolumeClaim" in v
    ]
    require(claims == ["data-postgres-0"])
    pvc = kube(["get", "pvc", claims[0], "-n", "fulfillflow", "-o", "json"])
    require(pvc["status"]["phase"] == "Bound")
    pv = kube(["get", "pv", pvc["spec"]["volumeName"], "-o", "json"])
    require(pv["status"]["phase"] == "Bound")
    claim = pv["spec"]["claimRef"]
    require(
        claim["uid"] == pvc["metadata"]["uid"]
        and claim["namespace"] == "fulfillflow"
        and claim["name"] == claims[0]
    )
    csi = pv["spec"]["csi"]
    require(csi["driver"] == "disk.csi.azure.com")
    return {
        "cluster_id": target["cluster_id"],
        "api_server": target["api_server"],
        "system_namespace_uid": system["metadata"]["uid"],
        "window": target["window"],
        "namespace": "fulfillflow",
        "pod_name": "postgres-0",
        "ready": True,
        "pod_uid": pod["metadata"]["uid"],
        "pvc_uid": pvc["metadata"]["uid"],
        "pv_uid": pv["metadata"]["uid"],
        "volume_handle": csi["volumeHandle"],
        "storage_driver": csi["driver"],
    }


def business(target: dict, get) -> dict:
    order = get(f"/api/v1/orders/{target['order_id']}")
    shipment = get(f"/api/v1/shipments/{target['shipment_id']}")
    events = get(f"/api/v1/shipments/{target['shipment_id']}/tracking?page_size=2")
    notification = get(f"/api/v1/notification-status/{target['event_id']}")
    require(order["id"] == target["order_id"] and order["status"] == "FULFILLED")
    require(
        shipment["id"] == target["shipment_id"]
        and shipment["order_id"] == order["id"]
        and shipment["status"] == "DELIVERED"
    )
    require(events["total"] == 1 and len(events["items"]) == 1)
    event = events["items"][0]
    require(
        event["id"] == target["event_id"]
        and event["application_result"] == "APPLIED"
        and event["resulting_shipment_status"] == "DELIVERED"
    )
    require(
        notification["tracking_event_id"] == target["event_id"]
        and notification["notification_id"] == target["notification_id"]
    )
    require(
        notification["processing"] == "DONE"
        and notification["status"] == "SIMULATED"
        and notification["required"] is True
    )
    return {
        **{k: target[k] for k in ("order_id", "shipment_id", "event_id", "notification_id")},
        "states": {
            "order": order["status"],
            "shipment": shipment["status"],
            "tracking": event["application_result"],
            "notification": notification["status"],
        },
    }


@contextmanager
def tunnel(prefix: list[str], log: Path):
    """Use only the tunnel started here; no fallback to an already listening process."""
    with log.open("xb") as stream:
        process = subprocess.Popen(
            prefix
            + [
                "-n",
                "fulfillflow",
                "port-forward",
                "service/core",
                ":8000",
                "--address",
                "127.0.0.1",
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                require(process.poll() is None)
                match = re.search(rb"Forwarding from 127\.0\.0\.1:(\d+) ->", log.read_bytes())
                if match:
                    yield f"http://127.0.0.1:{int(match[1])}", process
                    return
                time.sleep(0.1)
            raise ValueError("TUNNEL_NOT_READY")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("target", "kubeconfig", "kubectl", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--context", required=True)
    args = parser.parse_args()
    stage = "target_validation"
    output_created = False
    observations = []
    try:
        target = json.loads(args.target.read_bytes())
        validate_target(target)
        require(args.kubeconfig.is_file() and args.kubectl.is_file())
        args.output.mkdir(parents=True, exist_ok=False)
        output_created = True
        stage = "infrastructure_before"
        prefix = [
            str(args.kubectl.resolve()),
            "--kubeconfig",
            str(args.kubeconfig.resolve()),
            "--context",
            args.context,
            "--request-timeout=20s",
        ]

        def kube(command):
            result = subprocess.run(prefix + command, capture_output=True, check=True, timeout=30)
            return json.loads(result.stdout)

        before = infrastructure(target, kube)
        (args.output / "infrastructure-before.json").write_text(
            json.dumps(before, indent=2) + "\n", encoding="utf-8"
        )
        stage = "service_identity"
        # Bind the tunnel to a service materialized for this window, never a historical Core.
        service = kube(["get", "service", "core", "-n", "fulfillflow", "-o", "json"])
        require(service["metadata"]["labels"].get("fulfillflow.io/window") == target["window"])
        transport = HttpTransport()
        stage = "tunnel"
        with tunnel(prefix, args.output / "tunnel.private.log") as (base, process):

            def get(path):
                nonlocal stage
                stage = "business_http"
                require(process.poll() is None)
                response = transport("GET", base + path, {"Accept": "application/json"}, None, 5)
                observations.append(
                    {
                        "path": path,
                        "status": response.status,
                        "body_sha256": hashlib.sha256(response.body).hexdigest(),
                        "observed_at": datetime.now(UTC).isoformat(),
                    }
                )
                with (args.output / "queries.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(observations[-1]) + "\n")
                require(response.status == 200)
                stage = "business_contract"
                return json.loads(response.body)

            result = business(target, get)
        stage = "infrastructure_after"
        after = infrastructure(target, kube)
        require(before == after)
        result.update(before)
        result["observed_at"] = datetime.now(UTC).isoformat()
        result["queries"] = observations
        result["limit"] = (
            "Sequential selected observations, not atomic snapshot or backup. Cluster ARM ID is supplied; endpoint and namespace UID are checked."
        )
        (args.output / "capture.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps({"captured": True, "business_writes": 0, "resource_mutations": 0}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, Failure) as error:
        if output_created:
            (args.output / "failure.json").write_text(
                json.dumps(
                    {
                        "stage": stage,
                        "error_type": type(error).__name__,
                        "observed_responses": len(observations),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        print(json.dumps({"captured": False, "business_writes": 0, "resource_mutations": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
