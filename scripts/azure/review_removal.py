"""Review a saved Terraform JSON removal plan offline; never execute Terraform/Azure.

Inputs may contain secrets: keep the complete plan and approved inventory private.
The output contains only a digest and counts. Approval remains an operator decision.
"""

import argparse
import hashlib
import json
from pathlib import Path

ALLOWED_TYPES = {
    "azurerm_kubernetes_cluster",
    "azurerm_role_assignment",
    "azurerm_federated_identity_credential",
    "azurerm_user_assigned_identity",
}


def review(plan: dict, inventory: dict, *, targets: list[str] | None = None) -> dict:
    """Require exact address/type/ARM ID matches for every approved deletion."""
    if plan.get("errored") or (plan.get("complete") is not True and targets is None):
        raise ValueError("PLAN_NOT_COMPLETE")
    if plan.get("deferred_changes") or plan.get("resource_drift"):
        raise ValueError("PLAN_DEFERRED_OR_DRIFT")
    if not str(plan.get("format_version", "")).startswith("1."):
        raise ValueError("UNSUPPORTED_PLAN_FORMAT")
    expected = {}
    for item in inventory["delete"]:
        address, kind, resource_id = item["address"], item["type"], item["id"]
        if kind not in ALLOWED_TYPES or not isinstance(resource_id, str):
            raise ValueError("RESOURCE_TYPE_NOT_ALLOWED")
        if not resource_id.lower().startswith("/subscriptions/") or address in expected:
            raise ValueError("INVALID_APPROVED_IDENTITY")
        expected[address] = (kind, resource_id.lower())
    if not expected:
        raise ValueError("EMPTY_APPROVED_INVENTORY")
    if targets is not None:
        # Terraform sets complete=false for -target even without deferred changes.
        # Targets must come from the recorded invocation, never inferred from changes.
        if (
            not isinstance(targets, list)
            or not all(isinstance(value, str) for value in targets)
            or len(targets) != len(set(targets))
            or set(targets) != set(expected)
            or plan.get("applyable") is not True
            or not isinstance(plan.get("complete"), bool)
        ):
            raise ValueError("TARGETED_PLAN_CONTRACT")
    seen = set()
    for item in plan.get("resource_changes", []):
        actions = item["change"]["actions"]
        if actions == ["no-op"]:
            continue
        if item.get("mode") != "managed" or actions != ["delete"]:
            raise ValueError("NON_DELETE_CHANGE")
        address = item["address"]
        before = item["change"].get("before") or {}
        resource_id = before.get("id")
        if not isinstance(resource_id, str):
            raise ValueError("MISSING_RESOURCE_ID")
        if address in seen or expected.get(address) != (item["type"], resource_id.lower()):
            raise ValueError("DELETION_OUTSIDE_APPROVED_INVENTORY")
        seen.add(address)
    if seen != set(expected):
        raise ValueError("APPROVED_DELETION_MISSING")
    return {
        "offline_review": "passed",
        "approved_deletions": len(seen),
        "targeted": targets is not None,
        "full_configuration_convergence": plan.get("complete") is True,
        "execution_authorized": False,
        "limits": "Does not inspect AKS-managed resources, retained CSI disks, backups or billing.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--plan-binary", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--targets", type=Path, help="Private JSON array from the recorded -target invocation"
    )
    args = parser.parse_args()
    try:
        raw = args.plan.read_bytes()
        result = review(
            json.loads(raw),
            json.loads(args.inventory.read_bytes()),
            targets=json.loads(args.targets.read_bytes()) if args.targets else None,
        )
        result["plan_json_sha256"] = hashlib.sha256(raw).hexdigest()
        result["plan_binary_sha256"] = hashlib.sha256(args.plan_binary.read_bytes()).hexdigest()
        result["binary_json_correspondence_verified"] = False
        with args.output.open("x", encoding="utf-8") as target:
            json.dump(result, target, indent=2)
            target.write("\n")
    except (OSError, ValueError, KeyError, TypeError):
        # Never echo raw plan content, private paths or provider messages.
        print(json.dumps({"offline_review": "failed", "execution_authorized": False}))
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
