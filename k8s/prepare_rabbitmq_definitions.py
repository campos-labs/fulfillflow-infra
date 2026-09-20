"""Prepare broker definitions offline from protected password input; never deploy."""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

TEMPLATE = Path(__file__).parent / "assets" / "rabbitmq-definitions-template.json"
OWNERS = frozenset({"core", "tracking", "notifications"})


def build_definitions(passwords: dict[str, str]) -> dict:
    """Retain the audited topology/ACLs and create new salted SHA256 credentials."""
    if not isinstance(passwords, dict) or set(passwords) != OWNERS:
        raise ValueError("Exactly the three owner passwords are required")
    if any(not isinstance(value, str) or len(value) < 32 for value in passwords.values()):
        raise ValueError("Each owner password must have at least 32 characters")
    if len(set(passwords.values())) != 3:
        raise ValueError("Owner passwords must be distinct")
    result = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    for user in result["users"]:
        salt = secrets.token_bytes(4)
        digest = hashlib.sha256(salt + passwords[user["name"]].encode("utf-8")).digest()
        user["password_hash"] = base64.b64encode(salt + digest).decode("ascii")
    validate_definitions(result)
    return result


def validate_definitions(definitions: dict) -> None:
    """Reject topology drift, plaintext passwords, absent or malformed hashes."""
    expected = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    actual = copy.deepcopy(definitions)
    if not isinstance(actual, dict) or not isinstance(actual.get("users"), list):
        raise ValueError("Definitions must contain the expected users")
    try:
        for user in actual["users"]:
            if not isinstance(user, dict):
                raise ValueError("Invalid RabbitMQ user definition")
            encoded = user.pop("password_hash")
            if not isinstance(encoded, str) or len(base64.b64decode(encoded, validate=True)) != 36:
                raise ValueError("Invalid RabbitMQ SHA256 password hash")
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Invalid RabbitMQ SHA256 password hash") from exc
    if actual != expected:
        raise ValueError(
            "Definitions topology, owners or permissions differ from the audited template"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--passwords-file",
        type=Path,
        required=True,
        help="Protected JSON object with core, tracking and notifications passwords",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New protected definitions.json outside this repository",
    )
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parent.parent
    if any(path.resolve().is_relative_to(repo) for path in (args.passwords_file, args.output)):
        print("Input and output must be outside this repository.", file=sys.stderr)
        return 2
    try:
        passwords = json.loads(args.passwords_file.read_text(encoding="utf-8"))
        definitions = build_definitions(passwords)
        # O_EXCL prevents overwriting evidence or existing credentials. On Windows,
        # the containing directory must already have a protected user-only ACL.
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as destination:
            json.dump(definitions, destination, indent=2)
            destination.write("\n")
    except (OSError, ValueError, TypeError):
        print("Definitions preparation failed; no credentials were printed.", file=sys.stderr)
        return 1
    print("Protected definitions prepared; no Kubernetes resource was created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
