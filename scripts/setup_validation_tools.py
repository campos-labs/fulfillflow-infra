"""Install pinned portable validators; no PATH changes, Azure login or cluster access."""

import hashlib
import io
import json
import os
import platform
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def verified_payload(data: bytes, expected: str) -> bytes:
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("Downloaded validator checksum mismatch")
    return data


def install() -> None:
    config = json.loads((ROOT / "config/toolchain.json").read_text(encoding="utf-8"))
    system = platform.system().lower()
    if system not in {"windows", "linux"} or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise ValueError("This bootstrap supports only Windows/Linux amd64")
    for name, spec in config["downloads"][f"{system}_amd64"].items():
        suffix = ".exe" if system == "windows" else ""
        destination = ROOT / ".tools" / name / f"{name}{suffix}"
        destination.parent.mkdir(parents=True, exist_ok=True)
        # The checksum applies to the vendor artifact, including the Terraform ZIP.
        artifact = destination.parent / (
            "download.zip" if "archive_member" in spec else "download.bin"
        )
        if artifact.exists():
            data = verified_payload(artifact.read_bytes(), spec["sha256"])
        else:
            with urllib.request.urlopen(spec["url"], timeout=60) as response:
                data = response.read(150_000_001)
            if len(data) > 150_000_000:
                raise ValueError("Validator artifact exceeds size limit")
            verified_payload(data, spec["sha256"])
            artifact.write_bytes(data)
        if "archive_member" in spec:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                binary = archive.read(spec["archive_member"])
        else:
            binary = data
        if destination.exists():
            if destination.read_bytes() != binary:
                raise ValueError(
                    f"Existing {name} differs from pinned artifact; inspect explicitly"
                )
        else:
            destination.write_bytes(binary)
        if os.name != "nt":
            destination.chmod(0o755)
        print(f"Verified {name}: {destination}")


if __name__ == "__main__":
    try:
        install()
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"Validation tool preparation failed: {type(error).__name__}", file=sys.stderr)
        raise SystemExit(2) from None
