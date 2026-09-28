"""Verify selected AKS evidence and reproduce packages/diagram without Azure access."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import zipfile
from html import escape
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
ASSETS = ROOT / "docs/assets/aks-portability"
sys.path.insert(0, str(ROOT))

from scripts.azure.review_persistence import review  # noqa: E402
from scripts.http_trace_contract import verify_trace  # noqa: E402


def read(path):
    return json.loads(path.read_bytes())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(value, code):
    if not value:
        raise ValueError(code)


def verify_records():
    manifest = read(BASE / "manifest.json")
    declared = set()
    for entry in manifest["entries"]:
        path = (BASE / entry["path"]).resolve()
        require(path.is_relative_to((BASE / "records").resolve()), "RECORD_PATH")
        require(path not in declared, "DUPLICATE_RECORD")
        declared.add(path)
        data = path.read_bytes()
        require(digest(data) == entry["sha256"] and len(data) == entry["bytes"], "RECORD_HASH")
    require(
        declared == {p.resolve() for p in (BASE / "records").rglob("*") if p.is_file()}, "COVERAGE"
    )
    basic = BASE / "records/basic"
    smoke = read(basic / "smoke.json")
    require(
        all(
            smoke[k]
            for k in (
                "success",
                "acceptance_verified",
                "duplicate_verified",
                "tracking_completed",
                "order_completed",
                "notifications_simulated",
            )
        ),
        "SMOKE",
    )
    require(read(basic / "attempt-01.json")["complete"] is False, "FAILED_ATTEMPT_PRESERVED")
    require(read(basic / "attempt-02.json")["complete"] is True, "CONTINUATION")
    before, after = (read(basic / f"persistence-{phase}.json") for phase in ("before", "after"))
    require(review(before, after)["same_volume_and_result"], "PERSISTENCE")
    require(
        read(basic / "persistence-review.json")["intervening_operations"]
        == ["controlled_postgres_pod_recreation", "AKS_stop_start"],
        "INTERVENTIONS",
    )
    network = read(basic / "network.json")
    require(network["passed"] and network["target_pod_uid"] == after["pod_uid"], "NETWORK_TARGET")
    require([x["connected"] for x in network["observations"]] == [True, False, True], "NETWORK")
    probes = read(basic / "network-probes.json")
    require(len(probes) == 3, "PROBE_COUNT")
    for probe, observation in zip(probes, network["observations"], strict=True):
        require(probe["job"] == observation["job"], "PROBE_JOB")
        require(probe["result"]["connected"] == observation["connected"], "PROBE_RESULT")
        require(probe["result"]["errno"] == observation["errno"], "PROBE_ERRNO")
        require(
            probe["target_uid_before"] == probe["target_uid_after"] == after["pod_uid"],
            "PROBE_IDENTITY",
        )
        require(
            (probe["pod_labels"].get("fulfillflow.io/database-client") == "true")
            == observation["expected_connected"],
            "PROBE_LABEL",
        )
    volumes = read(basic / "pvcs.json")
    require(
        {v["claim_name"]: v["capacity"]["storage"] for v in volumes}
        == {"data-postgres-0": "32Gi", "data-rabbitmq-0": "16Gi"},
        "VOLUME_CAPACITY",
    )
    require(
        all(v["phase"] == "Bound" and v["driver"] == "disk.csi.azure.com" for v in volumes),
        "VOLUME_DRIVER",
    )
    require(read(basic / "kind-regression.json")["equal"], "KIND_BASELINE")
    http = BASE / "records/http"
    require(
        read(http / "capacity-attempt.json")["error"] == "NO_CAPACITY_FOR_DIAGNOSTICS",
        "CAPACITY_FAILURE",
    )
    actual = verify_trace(read(http / "trace-records.json"), read(http / "functional.json"))
    require(actual == read(http / "review.json"), "TRACE_REVIEW")
    functional = read(http / "functional.json")
    require(
        functional["status"] == 200 and functional["event_id"] == smoke["event_id"], "SAME_EVENT"
    )
    require(functional["offered_business_events"] == 0, "NO_NEW_EVENT")
    for phase in ("before", "after"):
        pending = read(http / f"pending-{phase}.json")
        require(
            all(v == 0 for s in ("core", "tracking", "notifications") for v in pending[s].values()),
            "DB_PENDING",
        )
        require(
            all(
                q["messages_ready"] == q["messages_unacknowledged"] == 0 for q in pending["broker"]
            ),
            "BROKER_PENDING",
        )
    for phase in ("before", "restored"):
        workloads = read(http / f"workloads-{phase}.json")
        require(
            len(workloads) == 6
            and all(w["replicas"] == w["ready_replicas"] == 1 for w in workloads),
            "WORKLOAD_RESTORATION",
        )
    summary = read(http / "summary.json")
    require(
        summary["complete"]
        and summary["workers_restored_verified"]
        and summary["stopped_verified"],
        "HTTP_CLEANUP",
    )
    require(
        not summary["diagnostic_cleanup_errors"] and not summary["worker_restore_errors"],
        "CLEANUP_ERRORS",
    )
    closure = BASE / "records/closure"
    require(read(closure / "summary.json")["execution_resources_absent_from_inventory"], "TEARDOWN")
    require(read(closure / "managed-group-exists.json") is False, "MANAGED_GROUP")
    require(read(closure / "disks-after.json")["value"] == [], "DISKS")
    types = {r["type"].lower() for r in read(closure / "inventory.json")}
    require(
        types
        == {
            "microsoft.storage/storageaccounts",
            "microsoft.containerregistry/registries",
            "microsoft.network/networkwatchers",
            "microsoft.billingbenefits/freeservices",
        },
        "RETAINED_INVENTORY",
    )
    for phase, filename in ((http, "workloads-active.png"), (closure, "resources-after.png")):
        require(
            digest((ASSETS / filename).read_bytes()) == read(phase / "portal.json")["sha256"],
            "SCREENSHOT_HASH",
        )
    return len(declared), actual


def figure(result):
    def t(x, y, text, size=20):
        return f'<text x="{x}" y="{y}" font-size="{size}">{escape(text)}</text>'

    body = [
        t(35, 48, "Portabilidade verificada em AKS", 30),
        t(
            35,
            82,
            "Um evento sintético; verificações complementares, sem comparação de desempenho",
            18,
        ),
    ]
    cards = [
        (
            35,
            "Aplicação 9e3a135",
            [
                "Admissão e duplicata verificadas",
                "Order / Tracking concluídos",
                "Notifications: simulação",
                "Sem nova carga nas continuações",
            ],
        ),
        (
            425,
            "Ambiente gerenciado",
            [
                "2 nós · Kubernetes 1.34.11",
                "Azure Disk: 32 Gi + 16 Gi",
                "Mesmo volume e resultado",
                "Rede: permitido → negado → permitido",
            ],
        ),
        (
            815,
            "Fatia HTTP 045e1ca",
            [
                "Workers suspensos sem pendências",
                "Uma consulta: HTTP 200",
                f"{result['spans']} spans; parentage verificado",
                "Workers restaurados ao final",
            ],
        ),
    ]
    for x, title, lines in cards:
        body.append(
            f'<rect x="{x}" y="120" width="350" height="210" rx="10" fill="#edf3f7" stroke="#a8bdcb"/>'
        )
        body.append(t(x + 16, 155, title, 22))
        for i, line in enumerate(lines):
            body.append(t(x + 16, 195 + i * 30, line, 17))
    body += [t(35, 385, "Correlação capturada na consulta saudável", 23)]
    labels = [
        ("Observador", "observer"),
        ("Core servidor", "core_server"),
        ("Core cliente", "internal_forwarding_including_content_type_check"),
        ("Tracking servidor", "tracking_server"),
    ]
    for i, (label, key) in enumerate(labels):
        x = 35 + i * 295
        body.append(
            f'<rect x="{x}" y="415" width="255" height="90" rx="8" fill="#e9f4ed" stroke="#99bba8"/>'
        )
        body.append(t(x + 15, 450, label, 21))
        body.append(t(x + 15, 481, f"{result['durations_ms'][key]:.2f} ms · span", 18))
        if i < 3:
            body.append(t(x + 262, 469, "→", 24))
    body += [
        t(
            35,
            550,
            "Setas representam parentage; durações aninhadas não são parcelas somáveis.",
            18,
        ),
        t(
            35,
            580,
            "Tracking → Core (metadados), SQL, AMQP e workers não têm spans nesta captura.",
            18,
        ),
        t(
            35,
            630,
            "Encerramento: AKS e execução removidos; ACR/state temporariamente retidos.",
            20,
        ),
        t(
            35,
            662,
            "Fontes: seleções JSON versionadas; inventário corresponde ao instante de encerramento.",
            17,
        ),
    ]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700" viewBox="0 0 1200 700" '
        'role="img" aria-labelledby="title desc"><title id="title">Portabilidade AKS e correlação HTTP</title>'
        '<desc id="desc">Resumo das verificações e quatro spans da consulta saudável isolada.</desc>'
        '<rect width="1200" height="700" fill="white"/><g font-family="Arial, sans-serif" fill="#183042">'
        + "".join(body)
        + "</g></svg>\n"
    ).encode("utf-8")


def archive(paths):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for name, path in sorted(paths.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 28, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            out.writestr(info, path.read_bytes())
    return stream.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="Regenerate diagram, ZIPs and derived hashes."
    )
    args = parser.parse_args()
    count, result = verify_records()
    artifacts = {ASSETS / "verified-boundaries.svg": figure(result)}
    for name, groups, screenshot in [
        ("portability", ("basic",), "workloads-active.png"),
        ("http-and-closure", ("http", "closure"), "resources-after.png"),
    ]:
        files = {
            "manifest.json": BASE / "manifest.json",
            "README.md": BASE / "README.md",
            "execution-sources.json": BASE / "records/execution-sources.json",
        }
        for group in groups:
            files.update(
                {
                    p.relative_to(BASE).as_posix(): p
                    for p in (BASE / "records" / group).glob("*.json")
                }
            )
        files["figures/" + screenshot] = ASSETS / screenshot
        artifacts[BASE / f"archives/{name}.zip"] = archive(files)
    hashes = {p.relative_to(ROOT).as_posix(): digest(data) for p, data in artifacts.items()}
    artifacts[BASE / "packages.json"] = (json.dumps(hashes, indent=2) + "\n").encode()
    artifacts[BASE / "archives/checksums.sha256"] = "".join(
        f"{digest(data)}  {p.name}\n" for p, data in artifacts.items() if p.suffix == ".zip"
    ).encode()
    for path, data in artifacts.items():
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        else:
            require(path.read_bytes() == data, f"DERIVED_CONTENT:{path.name}")
    print(
        json.dumps(
            {
                "verified": True,
                "records": count,
                "spans": result["spans"],
                "archives": 2,
                "azure_contacted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
