"""Validate drafts without reading cloud credentials or contacting a cluster."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

import jsonschema
import yaml

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], *, timeout: int = 180) -> str:
    result = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="strict",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        # Commands in this validator never contain credentials; retain useful static diagnostics.
        print(result.stdout, end="")
        print(result.stderr, end="", file=sys.stderr)
        raise RuntimeError(
            f"Validator {Path(command[0]).name} failed with exit {result.returncode}"
        )
    return result.stdout


def schema_name(document: dict) -> str:
    api = document["apiVersion"]
    kind = document["kind"]
    if not re.fullmatch(r"[a-zA-Z]+", kind) or not re.fullmatch(r"[a-z0-9./]+", api):
        raise ValueError("Invalid Kubernetes schema identity")
    version = api.replace("/", "-")
    if "/" in api:
        group, version = api.split("/", 1)
        # Generated Kubernetes schemas abbreviate API groups at the first dot.
        version = f"{group.split('.')[0]}-{version}"
    return f"{kind.lower()}-{version}.json"


def load_schema(document: dict, config: dict) -> dict:
    name = schema_name(document)
    folder = ROOT / ".cache" / "schemas" / config["schema_commit"]
    path = folder / name
    if not path.exists():
        folder.mkdir(parents=True, exist_ok=True)
        url = (
            "https://raw.githubusercontent.com/yannh/kubernetes-json-schema/"
            f"{config['schema_commit']}/v{config['schema_version']}-standalone-strict/{name}"
        )
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(4_000_001)
        if len(data) > 4_000_000:
            raise ValueError("Schema exceeds size limit")
        json.loads(data)
        path.write_bytes(data)
    return json.loads(path.read_bytes())


def validate_documents() -> None:
    for path in ROOT.rglob("*.md"):
        relative = path.relative_to(ROOT)
        if any(part.startswith(".") for part in relative.parts):
            continue
        source = path.read_text(encoding="utf-8")
        if source.count("```") % 2:
            raise ValueError(f"Unclosed code fence: {relative}")
        for target in re.findall(r"\]\(([^)]+)\)", source):
            if target.startswith(("https://", "http://", "#")):
                continue
            if not (path.parent / target.split("#")[0]).exists():
                raise ValueError(f"Broken local link: {relative}: {target}")


def save_manifest(path: Path, manifest: str) -> str:
    # Hash the exact delivered bytes, including on Windows with CRLF defaults.
    data = manifest.encode("utf-8")
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def validate(kubectl: Path, terraform: Path, output: Path) -> dict:
    config = json.loads((ROOT / "config/toolchain.json").read_text(encoding="utf-8"))
    if sys.version_info[:2] != (3, 12):
        raise ValueError("Python 3.12 is required by the validation lock")
    kube = json.loads(run([str(kubectl), "version", "--client", "-o", "json"]))
    tf = json.loads(run([str(terraform), "version", "-json"]))
    if (
        kube["clientVersion"]["gitVersion"] != config["kubectl"]
        or kube["kustomizeVersion"] != config["kustomize_embedded"]
        or tf["terraform_version"] != config["terraform"]
    ):
        raise ValueError("Validator version differs from config/toolchain.json")
    validate_documents()
    output.mkdir(parents=True, exist_ok=False)
    rendered = []
    for profile in ("example", "reduced-functional", "kind-local", "aks-portability"):
        for phase in ("foundations", "migrations", "runtime"):
            manifest = run([str(kubectl), "kustomize", f"k8s/overlays/{profile}/{phase}"])
            documents = [item for item in yaml.safe_load_all(manifest) if item is not None]
            for item in documents:
                jsonschema.validate(item, load_schema(item, config))
            digest = save_manifest(output / f"{profile}-{phase}.yaml", manifest)
            rendered.append(
                {
                    "profile": profile,
                    "phase": phase,
                    "objects": len(documents),
                    "sha256": digest,
                }
            )
    run([str(terraform), "fmt", "-check", "-recursive", "infra"])
    for directory in ("bootstrap", "environment"):
        prefix = [str(terraform), f"-chdir=infra/{directory}"]
        run(prefix + ["init", "-backend=false", "-input=false", "-lockfile=readonly"], timeout=300)
        run(prefix + ["validate", "-no-color"])
        tests = run(prefix + ["test", "-no-color"], timeout=300)
        (output / f"terraform-{directory}.txt").write_text(tests, encoding="utf-8")
    summary = {
        "result": "passed",
        "scope": "static_and_mock_validation_only",
        "cloud_contacted": False,
        "cluster_contacted": False,
        "kubectl": config["kubectl"],
        "terraform": config["terraform"],
        "schema_version": config["schema_version"],
        "rendered": rendered,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    suffix = ".exe" if os.name == "nt" else ""
    parser.add_argument(
        "--kubectl", type=Path, default=ROOT / ".tools/kubectl" / f"kubectl{suffix}"
    )
    parser.add_argument(
        "--terraform", type=Path, default=ROOT / ".tools/terraform" / f"terraform{suffix}"
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        for tool in (args.kubectl, args.terraform):
            if not tool.is_file():
                raise ValueError(f"Validator executable not found: {tool}")
        result = validate(args.kubectl.resolve(), args.terraform.resolve(), args.output.resolve())
        print(json.dumps(result))
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        RuntimeError,
        subprocess.SubprocessError,
        jsonschema.ValidationError,
        yaml.YAMLError,
    ) as error:
        print(f"Validation stopped: {type(error).__name__}: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
