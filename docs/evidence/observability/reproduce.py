"""Reproduce published observability selections and figures without cluster or network access."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from collections import defaultdict
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent
ASSETS = ROOT / "docs/assets/observability"
sys.path.insert(0, str(ROOT))

from scripts.http_trace_contract import verify_trace  # noqa: E402
from scripts.http_trace_fault import verify_fault  # noqa: E402
from scripts.verify_observability_evidence import require, verify  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def verify_http_manifest(directory):
    manifest = read(directory / "manifest.json")
    entries = manifest.get("files")
    if entries is None:
        entries = [entry for attempt in manifest["attempts"] for entry in attempt["files"]]
    declared = []
    for entry in entries:
        path = (directory / entry["path"]).resolve()
        require(path.is_relative_to(directory.resolve()), "MANIFEST_PATH")
        data = path.read_bytes()
        require(len(data) == entry["bytes"] and digest(data) == entry["sha256"], "HTTP_HASH")
        declared.append(path)
    actual = {p.resolve() for p in directory.rglob("*") if p.is_file()}
    require(len(set(declared)) == len(declared), "DUPLICATE_ENTRY")
    require(set(declared) | {(directory / "manifest.json").resolve()} == actual, "HTTP_COVERAGE")
    return len(entries)


def verify_http_cases(base):
    healthy = base / "http-05"
    actual = verify_trace(read(healthy / "trace-records.json"), read(healthy / "functional.json"))
    require(actual == read(healthy / "review.json"), "HEALTHY_REVIEW")
    fault = base / "http-fault-03"
    injection = read(fault / "injection.json")
    require(injection["endpoint_state"]["ready_endpoints"] == 0, "FAULT_ENDPOINTS")
    phases = []
    for phase in ("before", "fault", "after"):
        result = read(fault / phase / "functional.json")
        snapshot = read(fault / phase / "trace-records.json")
        actual = (
            verify_fault(snapshot, result, injection)
            if phase == "fault"
            else verify_trace(snapshot, result)
        )
        require(actual == read(fault / phase / "review.json"), "PHASE_REVIEW")
        require(result["offered_business_events"] == 0, "UNEXPECTED_OFFER")
        phases.append({"phase": phase, "status": result["status"], "spans": actual["spans"]})
    before = read(fault / "before/functional.json")
    after = read(fault / "after/functional.json")
    for key in ("event_id", "inbox_id", "tracking_event_id"):
        require(before[key] == after[key], "EVENT_IDENTITY")
    require(before["event_id"] == read(healthy / "functional.json")["event_id"], "REUSED_EVENT")
    restoration = read(fault / "restoration.json")
    pod = read(fault / "restored-pod.json")
    require(
        restoration["original_spec_restored"] and restoration["service_unchanged"], "RESTORATION"
    )
    require(pod["ready"] and pod["uid"] not in injection["previous_pod_uids"], "RESTORED_POD")
    require(read(fault / "restored-endpoints.json")["ready_endpoints"] > 0, "RESTORED_ENDPOINTS")
    require(
        read(fault / "preservation.json")["historical_deployment_specs_unchanged"], "PRESERVATION"
    )
    summary = read(fault / "summary.json")
    require(summary["complete"] and summary["container_stopped"], "SHUTDOWN")
    require(summary["business_writes"] == 0, "BUSINESS_WRITES")
    require(read(fault / "protocol.json")["query_count"] == 3, "QUERY_COUNT")
    snapshot = read(fault / "after/trace-records.json")
    require(len({r["span_id"] for r in snapshot["records"]}) == 11, "DISTINCT_SPANS")
    require(snapshot["accepted_batches"] == 8 and snapshot["rejected_batches"] == 0, "BATCHES")
    return phases


def text(x, y, value, size=20, color="#183042", bold=False):
    weight = ' font-weight="600"' if bold else ""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}"{weight}>'
        f"{escape(str(value))}</text>"
    )


def box(x, y, width, height, color="#edf3f7", stroke="#a8bdcb"):
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="10" '
        f'fill="{color}" stroke="{stroke}"/>'
    )


def arrow(x1, y1, x2, y2):
    return (
        f'<path d="M {x1} {y1} L {x2} {y2}" fill="none" stroke="#527184" '
        'stroke-width="2" marker-end="url(#arrow)"/>'
    )


def svg(title, description, height, elements):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="{height}" '
        f'viewBox="0 0 1200 {height}" role="img" aria-labelledby="title desc">'
        f'<title id="title">{escape(title)}</title><desc id="desc">{escape(description)}</desc>'
        '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        '<path d="M 0 0 L 10 5 L 0 10 z" fill="#527184"/></marker></defs>'
        f'<rect width="1200" height="{height}" fill="white"/>'
        '<g font-family="Arial, sans-serif">' + "".join(elements) + "</g></svg>\n"
    ).encode("utf-8")


def figures(base, phases):
    workers = read(base / "records/healthy-01/worker-records.json")
    messages = defaultdict(list)
    for worker in workers.values():
        for row in worker["records"]:
            if "message_id" in row:
                messages[row["message_id"]].append(row)
    links = []
    for rows in messages.values():
        ordered = [
            next(row for row in rows if row["outcome"] == stage)
            for stage in ("SENT", "PERSISTED", "DONE")
        ]
        links.append(ordered)
    links.sort(
        key=lambda rows: (rows[0]["service"] != "tracking", rows[1]["service"] != "tracking")
    )
    healthy = read(base / "http-05/functional.json")
    spans = [
        r
        for r in read(base / "http-05/trace-records.json")["records"]
        if r["trace_id"] == healthy["trace_id"]
    ]
    ordered_spans = []
    parent = None
    for _ in spans:
        row = next(r for r in spans if r["parent_span_id"] == parent)
        ordered_spans.append(row)
        parent = row["span_id"]
    elements = [
        text(40, 46, "Coberturas complementares", 30, bold=True),
        text(
            40,
            80,
            "Casos de workers e consulta HTTP: evidências distintas, sem comparação de ferramentas.",
            20,
        ),
        text(40, 126, "CORRELAÇÃO EXISTENTE  ·  mensagens ligadas por IDs", 19, bold=True),
    ]
    for i, rows in enumerate(links):
        y = 148 + i * 80
        for j, row in enumerate(rows):
            x = 40 + j * 400
            elements.extend(
                [
                    box(x, y, 320, 60),
                    text(x + 15, y + 25, row["service"].capitalize(), bold=True),
                    text(x + 15, y + 48, row["outcome"], 18),
                ]
            )
            if j < 2:
                elements.append(arrow(x + 327, y + 30, x + 387, y + 30))
    elements.extend(
        [
            text(
                40,
                422,
                f"{len(messages)} mensagens · 9 registros por evento · resultado público conferido separadamente",
                19,
            ),
            text(40, 474, "OPENTELEMETRY  ·  parentela dos spans HTTP", 19, bold=True),
            text(
                40,
                505,
                "Cada caixa abaixo representa um span; Core possui operações servidor e cliente.",
                18,
            ),
        ]
    )
    for i, row in enumerate(ordered_spans):
        x = 40 + 292 * i
        role = "CLIENT" if row["kind"] == "SPAN_KIND_CLIENT" else "SERVER"
        name = row["service"].removeprefix("httpdiag-").replace("observer", "observador")
        elements.extend(
            [
                box(x, 530, 244, 65, "#eaf4f0", "#88b6a4"),
                text(x + 15, 556, name.capitalize(), bold=True),
                text(x + 15, 581, role, 18),
            ]
        )
        if i < len(ordered_spans) - 1:
            elements.append(arrow(x + 250, 562, x + 284, 562))
    elements.extend(
        [
            '<path d="M 1040 602 L 1040 650 L 930 650" fill="none" '
            'stroke="#8c7255" stroke-width="2" stroke-dasharray="6 5" marker-end="url(#arrow)"/>',
            box(400, 615, 520, 70, "#fbf4eb", "#b49b7d"),
            text(418, 642, "Core: consulta de metadados", 20, "#775432", True),
            text(418, 670, "Operação adicional sem spans nesta fatia", 18, "#775432"),
            text(
                40,
                714,
                "Sem tracing de workers, AMQP ou SQL. Ligações não representam duração.",
                19,
            ),
            text(
                40,
                745,
                "Fontes: records/healthy-01/worker-records.json e http-05/trace-records.json",
                15,
                "#526979",
            ),
        ]
    )
    coverage = svg(
        "Cobertura de correlação e HTTP",
        "Três mensagens por IDs e quatro spans HTTP; metadados, SQL e AMQP fora da cobertura de tracing.",
        770,
        elements,
    )
    elements = [
        text(40, 46, "Consulta durante uma interrupção controlada", 30, bold=True),
        text(
            40,
            80,
            "Mesmo evento já concluído · três GETs · nenhum webhook ou escrita de negócio",
            20,
        ),
    ]
    titles = {"before": "Antes", "fault": "Interrupção", "after": "Depois"}
    labels = {
        "before": ["Resultado confirmado", "pela consulta pública", "Tracking disponível"],
        "fault": [
            "Estado do negócio inconclusivo",
            "Cliente Core: transport",
            "Sem pods / endpoints Tracking",
        ],
        "after": [
            "Mesmo resultado confirmado",
            "Novo pod Ready e endpoint",
            "Restauração pelo executor",
        ],
    }
    for i, phase in enumerate(phases):
        x = 40 + 396 * i
        fault = phase["phase"] == "fault"
        elements.extend(
            [
                box(x, 120, 328, 280, "#fff4e7" if fault else "#eaf4f0"),
                text(x + 18, 157, titles[phase["phase"]], 24, bold=True),
                text(x + 18, 207, f"HTTP {phase['status']}", 34, bold=True),
                text(x + 18, 247, f"{phase['spans']} spans", 25),
            ]
        )
        for j, label in enumerate(labels[phase["phase"]]):
            elements.append(text(x + 18, 294 + j * 30, label, 18))
        if i < 2:
            elements.append(arrow(x + 336, 228, x + 384, 228))
    elements.extend(
        [
            text(
                40,
                447,
                "Localização sustentada pela intervenção + erro do cliente + cobertura conhecida.",
                21,
                bold=True,
            ),
            text(
                40,
                483,
                "Ausência de span, isoladamente, não identifica a causa nem prova ausência de processamento.",
                19,
            ),
            text(
                40,
                519,
                "4 + 3 + 4 = 11 spans distintos. Snapshots cumulativos são filtrados pelo trace de cada fase.",
                19,
            ),
            text(
                40,
                558,
                "Fonte: http-fault-03/{before,fault,after}, injection.json e registros de restauração",
                15,
                "#526979",
            ),
        ]
    )
    sequence = svg(
        "Consulta saudável, falha de transporte e restauração",
        "200 com quatro spans; 503 com três spans e erro de transporte; 200 com quatro spans após restauração. Estado confirmado antes e depois, inconclusivo durante.",
        585,
        elements,
    )
    return {"coverage.svg": coverage, "http-sequence.svg": sequence}


def members(base, group):
    if group == "correlation":
        paths = sorted((base / "records").rglob("*.json")) + sorted(
            (base / "records").rglob("*.jsonl")
        )
        metadata = [
            "manifest.json",
            "healthy-01-review.json",
            "pending-02-review.json",
            "discovery-01.json",
        ]
        data = {
            p.relative_to(base).as_posix(): (p.read_bytes(), "original selected capture")
            for p in paths
        }
        for name in metadata:
            data[name] = (
                base.joinpath(name).read_text(encoding="utf-8").encode("utf-8"),
                "derived metadata; UTF-8/LF",
            )
        scope = "Dois casos de workers, preparação e descoberta retrospectiva identificada como contexto."
    else:
        paths = [
            p
            for name in ("http-05", "http-errors", "http-fault-03")
            for p in (base / name).rglob("*")
            if p.is_file()
        ]
        data = {
            p.relative_to(base).as_posix(): (
                p.read_bytes(),
                "published capture or selection manifest; exact bytes",
            )
            for p in paths
        }
        scope = "Consulta saudável, erros preparatórios e sequência controlada; snapshots cumulativos por trace_id."
    index = (
        f"# Evidências: {group}\n\n{scope}\n\n"
        "Os manifestos identificam fontes, hashes e exclusões; review.json é conferência derivada.\n"
        "Protocolos identificam as referências medidas. Falhas preparatórias não são casos aprovados.\n"
        "Sem imagens, bancos, segredos ou garantia de recriar o ambiente.\n\n"
        "Relatório e reprodutor: docs/OBSERVABILITY_EVALUATION.md e\n"
        "docs/evidence/observability/reproduce.py no repositório fulfillflow-infra.\n"
        "Este pacote permite leitura independente; a conferência executável usa o checkout.\n"
    )
    data["INDEX.md"] = (index.encode("utf-8"), "generated package index")
    return dict(sorted(data.items()))


def archive_bytes(entries):
    buffer = io.BytesIO()
    # Stored entries keep byte identity across Python/zlib versions; selections are small.
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, (payload, _) in entries.items():
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    return buffer.getvalue()


def run(write=False):
    correlation = verify(BASE)
    count = sum(
        verify_http_manifest(BASE / name) for name in ("http-05", "http-errors", "http-fault-03")
    )
    phases = verify_http_cases(BASE)
    outputs = {}
    packages = []
    for name in ("correlation", "http"):
        entries = members(BASE, name)
        payload = archive_bytes(entries)
        relative = f"archives/{name}.zip"
        outputs[BASE / relative] = payload
        packages.append(
            {
                "path": relative,
                "sha256": digest(payload),
                "bytes": len(payload),
                "files": [
                    {"path": p, "bytes": len(b), "sha256": digest(b), "representation": r}
                    for p, (b, r) in entries.items()
                ],
            }
        )
    derived = figures(BASE, phases)
    for name, payload in derived.items():
        outputs[ASSETS / name] = payload
    manifest = {
        "schema_version": 1,
        "purpose": "Offline inspection, not runtime reproduction",
        "archives": packages,
        "figures": [
            {"path": f"docs/assets/observability/{name}", "sha256": digest(data)}
            for name, data in derived.items()
        ],
        "load_executed": False,
    }
    outputs[BASE / "packages.json"] = json_bytes(manifest)
    for path, payload in outputs.items():
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        else:
            require(path.read_bytes() == payload, f"GENERATED_ARTIFACT_DIFFERS: {path.name}")
    return {
        "verified": True,
        "correlation": correlation,
        "http_files_verified": count,
        "controlled_phases": phases,
        "archives": len(packages),
        "figures": len(derived),
        "load_executed": False,
        "generated": write,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Regenerate packages and figures from verified records"
    )
    print(json.dumps(run(parser.parse_args().write), indent=2))
