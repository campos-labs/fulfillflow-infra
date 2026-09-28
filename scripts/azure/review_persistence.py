"""Compare captured persistence observations offline; never delete pods or query APIs."""

import argparse
import json
from pathlib import Path


def review(before: dict, after: dict) -> dict:
    for capture in (before, after):
        if capture.get("namespace") != "fulfillflow" or capture.get("pod_name") != "postgres-0":
            raise ValueError("UNEXPECTED_TARGET")
        if (
            capture.get("ready") is not True
            or capture.get("storage_driver") != "disk.csi.azure.com"
        ):
            raise ValueError("AZURE_DISK_NOT_READY")
        for key in (
            "cluster_id",
            "pod_uid",
            "pvc_uid",
            "pv_uid",
            "volume_handle",
            "event_id",
            "order_id",
            "shipment_id",
            "notification_id",
        ):
            if not isinstance(capture.get(key), str) or not capture[key]:
                raise ValueError("IDENTITY_MISSING")
        if capture.get("states") != {
            "order": "FULFILLED",
            "shipment": "DELIVERED",
            "tracking": "APPLIED",
            "notification": "SIMULATED",
        }:
            raise ValueError("FUNCTIONAL_RESULT_UNCONFIRMED")
    if before["pod_uid"] == after["pod_uid"]:
        raise ValueError("POD_NOT_RECREATED")
    for key in (
        "cluster_id",
        "pvc_uid",
        "pv_uid",
        "volume_handle",
        "event_id",
        "order_id",
        "shipment_id",
        "notification_id",
    ):
        if before[key] != after[key]:
            raise ValueError("PERSISTENCE_IDENTITY_CHANGED")
    return {
        "review": "passed",
        "pod_recreated": True,
        "same_volume_and_result": True,
        "limit": "Captured observations require independent provenance; not a backup restore or HA test.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = review(json.loads(args.before.read_bytes()), json.loads(args.after.read_bytes()))
        with args.output.open("x", encoding="utf-8") as target:
            json.dump(result, target, indent=2)
            target.write("\n")
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"review": "failed"}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
