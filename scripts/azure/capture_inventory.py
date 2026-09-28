"""Read subscription resource inventory with explicit scope; no mutations or billing claim."""

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


def collect(subscription: str, get) -> dict:
    if str(UUID(subscription)) != subscription:
        raise ValueError("INVALID_SUBSCRIPTION")
    prefix = f"/subscriptions/{subscription}/"
    url = f"https://management.azure.com/subscriptions/{subscription}/resources?api-version=2021-04-01"
    seen_pages = set()
    resources = {}
    for _ in range(100):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "management.azure.com"
            or parsed.path.lower() != prefix.lower() + "resources"
            or parsed.fragment
            or url in seen_pages
        ):
            raise ValueError("INVALID_INVENTORY_PAGE")
        seen_pages.add(url)
        page = get(url)
        for resource in page["value"]:
            identity = resource["id"]
            if not identity.lower().startswith(prefix.lower()) or identity.lower() in resources:
                raise ValueError("INVENTORY_IDENTITY_MISMATCH")
            resources[identity.lower()] = {key: resource[key] for key in ("id", "type", "location")}
        url = page.get("nextLink")
        if not url:
            return {
                "observed_at": datetime.now(UTC).isoformat(),
                "subscription_id": subscription,
                "resources": sorted(resources.values(), key=lambda item: item["id"].lower()),
                "pages": len(seen_pages),
                "complete": True,
                "limit": "ARM inventory is not billing, deletion confirmation or exhaustive child-resource enumeration. Compare approved IDs and inspect retained groups/disks separately.",
            }
    raise ValueError("PAGE_LIMIT")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--az", type=Path, required=True)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or not args.az.is_file():
            raise ValueError("INVALID_PATH")

        def get(url):
            result = subprocess.run(
                [
                    str(args.az.resolve()),
                    "rest",
                    "--method",
                    "get",
                    "--url",
                    url,
                    "--resource",
                    "https://management.azure.com/",
                    "--subscription",
                    args.subscription,
                    "--only-show-errors",
                    "--output",
                    "json",
                ],
                capture_output=True,
                check=True,
                timeout=60,
            )
            return json.loads(result.stdout)

        result = collect(args.subscription, get)
        with args.output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        print(
            json.dumps(
                {"inventory_complete": True, "resources": len(result["resources"]), "mutations": 0}
            )
        )
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({"inventory_complete": False, "mutations": 0}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
