"""Compare Kind renders with frozen v1.2.0-rc.1, offline and without checking out files."""

import argparse
import hashlib
import io
import json
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = "777900da060419acf559dec56902ef1e326504cf"
PHASES = ("foundations", "migrations", "runtime")


def run(command: list[str], root: Path) -> bytes:
    return subprocess.run(command, cwd=root, check=True, capture_output=True, timeout=90).stdout


def extract_tree(data: bytes, destination: Path) -> None:
    # Only regular files/directories in k8s; no links or paths outside the temporary tree.
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        for item in archive:
            path = PurePosixPath(item.name)
            if path.is_absolute() or ".." in path.parts or path.parts[0] != "k8s":
                raise ValueError("UNSAFE_ARCHIVE_PATH")
            if not (item.isfile() or item.isdir()):
                raise ValueError("UNSUPPORTED_ARCHIVE_ENTRY")
            target = destination.joinpath(*path.parts)
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(item) as source:
                    target.write_bytes(source.read())


def compare(reference: bytes, current: bytes) -> dict:
    # Same renderer, normalizing only OS line endings; no ignored fields or diff allowlist.
    reference = reference.replace(b"\r\n", b"\n")
    current = current.replace(b"\r\n", b"\n")
    return {
        "equal": reference == current,
        "reference_sha256": hashlib.sha256(reference).hexdigest(),
        "current_sha256": hashlib.sha256(current).hexdigest(),
    }


def verify(root: Path, kubectl: Path) -> dict:
    baseline_tools = json.loads(run(["git", "show", f"{REFERENCE}:config/toolchain.json"], root))
    actual_tools = json.loads(run([str(kubectl), "version", "--client", "-o", "json"], root))
    if (
        actual_tools["clientVersion"]["gitVersion"] != baseline_tools["kubectl"]
        or actual_tools["kustomizeVersion"] != baseline_tools["kustomize_embedded"]
    ):
        raise ValueError("BASELINE_RENDERER_REQUIRED")
    data = run(["git", "archive", "--format=tar", REFERENCE, "k8s"], root)
    results = {}
    with tempfile.TemporaryDirectory(prefix="fulfillflow-kind-regression-") as temporary:
        baseline = Path(temporary)
        extract_tree(data, baseline)
        for phase in PHASES:
            relative = f"k8s/overlays/kind-local/{phase}"
            reference = run([str(kubectl), "kustomize", str(baseline / relative)], root)
            current = run([str(kubectl), "kustomize", str(root / relative)], root)
            results[phase] = compare(reference, current)
    return {
        "reference": REFERENCE,
        "release": "v1.2.0-rc.1",
        "equal": all(item["equal"] for item in results.values()),
        "phases": results,
        "cluster_contacted": False,
        "limit": "Render equality does not establish runtime or cross-environment causality.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = ".exe" if os.name == "nt" else ""
    parser.add_argument("--kubectl", type=Path, default=ROOT / f".tools/kubectl/kubectl{suffix}")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("OUTPUT_EXISTS")
        result = verify(ROOT, args.kubectl.resolve())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as target:
            json.dump(result, target, indent=2)
            target.write("\n")
        print(json.dumps(result))
        return 0 if result["equal"] else 1
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.SubprocessError):
        print(json.dumps({"equal": False, "error": "REGRESSION_CHECK_FAILED"}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
