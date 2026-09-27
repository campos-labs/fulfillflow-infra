"""Read the published ZIPs and reproduce the descriptive tables and figures offline.

Default: verify archives and original manifests, then report descriptive totals.
--output NEW_DIRECTORY: also write CSV/JSON tables. --plots needs matplotlib 3.10.8.
No cluster, private directory, shell command, extraction or original-file mutation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import zipfile
from collections import Counter
from pathlib import Path

BASE = Path(__file__).resolve().parent
CONDITIONS = ("fixed-1", "fixed-2", "adaptive")
LABELS = {"fixed-1": "1 fixa", "fixed-2": "2 fixas", "adaptive": "Adaptativa"}
COLORS = {"fixed-1": "#236a9a", "fixed-2": "#23816c", "adaptive": "#b45b28"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def close(actual, expected, context):
    require(math.isclose(actual, expected, abs_tol=1e-6), context)


def read_evidence():
    manifest = json.loads((BASE / "manifest.json").read_bytes())
    summary = json.loads((BASE / "comparison-summary.projection.json").read_bytes())
    review = json.loads((BASE / "review.projection.json").read_bytes())
    for f in manifest["files"]:
        if "archive" not in f:
            require(sha((BASE / f["path"]).read_bytes()) == f["sha256"], f["path"])
    rows, series, outcomes = [], [], []
    preserved = {r["attempt"]: r for r in summary["results"]}
    verified = 0
    for archive in manifest["archives"]:
        path = BASE / archive["path"]
        require(sha(path.read_bytes()) == archive["sha256"], "ZIP hash: " + path.name)
        with zipfile.ZipFile(path) as z:
            require(len(z.namelist()) == len(set(z.namelist())), "Duplicate ZIP member")
            for f in manifest["files"]:
                if f.get("archive") == archive["path"]:
                    require(sha(z.read(f["path"])) == f["sha256"], f["path"])
            for a in manifest["attempts"]:
                if a["archive"] != archive["path"]:
                    continue
                name = a["attempt"]
                prefix = a["root"] + "/"

                def read(relative):
                    return json.loads(z.read(prefix + relative))

                def lines(relative):
                    return [json.loads(s) for s in z.read(prefix + relative).splitlines()]

                for line in z.read(prefix + "checksums.sha256").decode().splitlines():
                    expected, relative = line.split(maxsplit=1)
                    relative = relative.lstrip("*").replace("\\", "/")
                    require(sha(z.read(prefix + relative)) == expected, prefix + relative)
                    verified += 1
                result = read("comparison-result.json")
                require(result == preserved[name]["result"], "Summary mismatch: " + name)
                events = read("measurement/events.json")
                counts = Counter(e["classification"] for e in events)
                require(dict(counts) == result["counts"], "Outcome counts: " + name)
                require(len(events) == result["planned"] == result["accepted"] == 1020, name)
                latencies = sorted(
                    e["completed_monotonic"] - e["acceptance"]["monotonic"] for e in events
                )
                close(
                    latencies[math.ceil(0.95 * len(latencies)) - 1],
                    result["confirmation_observed_seconds"]["p95"],
                    "p95: " + name,
                )
                samples = lines("measurement/series.jsonl")
                window = read("measurement/window.json")
                inventories = [s["pod_inventory"] for s in samples]
                require(
                    inventories[0]["observed_monotonic"] <= window["start"]
                    and inventories[-1]["observed_monotonic"] >= window["end"],
                    name,
                )
                pod_seconds = 0
                for x, y in zip(inventories, inventories[1:]):
                    gap = y["observed_monotonic"] - x["observed_monotonic"]
                    require(0 < gap <= 10, "Inventory coverage: " + name)
                    duration = max(
                        0,
                        min(window["end"], y["observed_monotonic"])
                        - max(window["start"], x["observed_monotonic"]),
                    )
                    pod_seconds += duration * len(x["pods"])
                close(pod_seconds, result["pod_time"]["existing_pod_seconds"], name)
                close(max(s["inbox"]["eligible"] for s in samples), result["max_eligible"], name)
                actual = read("measurement/actual-controller.json")
                condition = result["condition"]
                expected_range = (1, 2) if condition == "adaptive" else (int(condition[-1]),) * 2
                require(
                    (actual["minReplicaCount"], actual["maxReplicaCount"]) == expected_range,
                    "Applied controller: " + name,
                )
                rows.append(
                    {
                        "attempt": name,
                        "condition": condition,
                        "block": int(name[1]),
                        "position": int(name[4]),
                        "session": preserved[name]["session"],
                        "planned": result["planned"],
                        "accepted": result["accepted"],
                        "confirmed_in_time": counts["completed_in_time"],
                        "confirmed_late": counts["completed_late"],
                        "confirmed_in_time_percent": 100
                        * counts["completed_in_time"]
                        / len(events),
                        "p95_observed_seconds": result["confirmation_observed_seconds"]["p95"],
                        "existing_pod_seconds": pod_seconds,
                        "peak_eligible": result["max_eligible"],
                        "peak_age_seconds": result["max_oldest_eligible_seconds"],
                        "observed_drain_seconds": result["observed_confirmation_drain_seconds"],
                        "http_non_200": result["http_observation"]["non_200"],
                        "min_host_available_gib": result["min_host_available_gib"],
                    }
                )
                for s in samples:
                    inv, ctrl = s["pod_inventory"], s["controller"]
                    series.append(
                        {
                            "attempt": name,
                            "condition": condition,
                            "inbox_offset_seconds": s["inbox_observed_monotonic"] - window["start"],
                            "eligible": s["inbox"]["eligible"],
                            "oldest_eligible_seconds": s["inbox"]["oldest_eligible_seconds"],
                            "inventory_offset_seconds": inv["observed_monotonic"] - window["start"],
                            "existing": len(inv["pods"]),
                            "ready": sum(p["ready"] for p in inv["pods"]),
                            "controller_offset_seconds": ctrl["monotonic"] - window["start"],
                            "desired": ctrl["hpa_status"]["desiredReplicas"],
                        }
                    )
                for e in events:
                    outcomes.append(
                        {
                            "attempt": name,
                            "event_id": e["event_id"],
                            "classification": e["classification"],
                            "confirmation_observed_seconds": e["completed_monotonic"]
                            - e["acceptance"]["monotonic"],
                        }
                    )
    rows.sort(key=lambda r: (r["block"], r["position"]))
    require(len(rows) == 9, "Nine attempts required")
    stats = {
        c: {
            "attempts": 3,
            **{
                k: statistics.median(r[k] for r in rows if r["condition"] == c)
                for k in [
                    "confirmed_in_time_percent",
                    "p95_observed_seconds",
                    "existing_pod_seconds",
                    "peak_eligible",
                    "peak_age_seconds",
                    "observed_drain_seconds",
                ]
            },
        }
        for c in CONDITIONS
    }
    totals = {
        k: sum(r[k] for r in rows)
        for k in ["planned", "accepted", "confirmed_in_time", "confirmed_late", "http_non_200"]
    }
    require(totals["accepted"] == review["total_accepted"], "Review total")
    require(totals["confirmed_late"] == review["total_counts"]["completed_late"], "Review late")
    return (
        rows,
        series,
        outcomes,
        {
            "totals": totals,
            "condition_medians": stats,
            "original_manifest_entries_verified": verified,
            "method": "Medians between attempts; no pooled event percentile; no significance claim.",
        },
    )


def csv_write(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plots(output, rows, samples):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    require(matplotlib.__version__ == "3.10.8", "Use matplotlib 3.10.8 for frozen figures")
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "svg.hashsalt": "fulfillflow-scaling-1",
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )

    def save(fig, name):
        svg = output / (name + ".svg")
        fig.savefig(svg, metadata={"Date": None})
        # Matplotlib paths contain trailing spaces; normalize the published text.
        svg.write_text(
            "\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines())
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
        fig.savefig(output / (name + ".png"), dpi=150)
        plt.close(fig)

    fig, axs = plt.subplots(1, 2, figsize=(12, 6), layout="constrained")
    y = list(range(9))
    labels = [r["attempt"] + (" *" if r["attempt"] == "b1-p1-adaptive" else "") for r in rows]
    for ax, field, title, xmax in [
        (axs[0], "confirmed_in_time_percent", "Confirmação observada em até 60 s (%)", 115),
        (axs[1], "existing_pod_seconds", "Pods existentes na janela comum (pod-s)", 1040),
    ]:
        values = [r[field] for r in rows]
        ax.barh(y, values, color=[COLORS[r["condition"]] for r in rows], height=0.64)
        for i, value in enumerate(values):
            ax.text(
                value + xmax * 0.013,
                i,
                f"{value:.1f}" if field.endswith("percent") else f"{value:.0f}",
                va="center",
            )
        ax.set(yticks=y, yticklabels=labels if ax is axs[0] else [], xlim=(0, xmax), title=title)
        ax.invert_yaxis()
        ax.grid(axis="x", alpha=0.18)
        ax.set_axisbelow(True)
    fig.suptitle("Capacidade fixa e adaptativa · nove tentativas individuais", fontsize=15)
    fig.supxlabel(
        "* Primeira sessão; interrupção entre tentativas no bloco 1. Janela: 450 s. Pod-tempo não é custo financeiro.",
        fontsize=9,
    )
    save(fig, "outcomes")

    fig, axs = plt.subplots(3, 3, figsize=(12, 8), sharex=True, sharey=True, layout="constrained")
    for i, c in enumerate(CONDITIONS):
        for j, block in enumerate([1, 2, 3]):
            row = next(r for r in rows if r["condition"] == c and r["block"] == block)
            data = [s for s in samples if s["attempt"] == row["attempt"]]
            ax = axs[i, j]
            ax.axvspan(15, 75, color="#ecd3ab", alpha=0.5)
            ax.plot(
                [s["inbox_offset_seconds"] for s in data],
                [s["eligible"] for s in data],
                color=COLORS[c],
                marker=".",
                markersize=3,
            )
            ax.set(title=row["attempt"], xlim=(0, 160), ylim=(0, 220), xticks=[0, 15, 75, 90, 150])
            ax.grid(alpha=0.18)
            if j == 0:
                ax.set_ylabel(LABELS[c] + "\nMensagens elegíveis")
    fig.suptitle(
        "Pendência elegível do core-worker · mesmas escalas em todas as tentativas", fontsize=14
    )
    fig.supxlabel(
        "Segundos desde a primeira oferta agendada · faixa sombreada: patamar de 16/s · linhas ligam amostras, não medição contínua",
        fontsize=9,
    )
    save(fig, "backlog")

    fig, axs = plt.subplots(3, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for ax, r in zip(axs, [r for r in rows if r["condition"] == "adaptive"]):
        data = [s for s in samples if s["attempt"] == r["attempt"]]
        ax.axvspan(15, 75, color="#ecd3ab", alpha=0.5)
        for field, clock, color, style in [
            ("desired", "controller_offset_seconds", "#674fa3", ":"),
            ("existing", "inventory_offset_seconds", "#b45b28", "-"),
            ("ready", "inventory_offset_seconds", "#236a9a", "--"),
        ]:
            label = {
                "desired": "Desejadas pelo HPA",
                "existing": "Pods existentes",
                "ready": "Pods Ready",
            }[field]
            ax.step(
                [s[clock] for s in data],
                [s[field] for s in data],
                where="post",
                color=color,
                linestyle=style,
                linewidth=2,
                label=label,
            )
        ax.set(
            title=r["attempt"], yticks=[1, 2], ylim=(0.85, 2.2), xlim=(0, 450), ylabel="Réplicas"
        )
        ax.grid(alpha=0.18)
    axs[0].legend(loc="upper right", ncol=3, fontsize=9)
    fig.suptitle("Adaptação observada · solicitação, existência e prontidão", fontsize=14)
    fig.supxlabel(
        "Segundos desde a primeira oferta agendada · faixa: patamar de 16/s · leituras não atômicas; transições têm resolução amostral",
        fontsize=9,
    )
    save(fig, "replicas")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plots", action="store_true")
    args = parser.parse_args()
    require(not args.plots or args.output is not None, "--plots requires --output")
    if args.output:
        require(not args.output.exists(), "Output must be a new directory")
    rows, series, events, stats = read_evidence()
    if args.output:
        args.output.mkdir(parents=True)
        csv_write(args.output / "attempts.csv", rows)
        csv_write(args.output / "series.csv", series)
        csv_write(args.output / "events.csv", events)
        (args.output / "statistics.json").write_text(
            json.dumps(stats, indent=2) + "\n", encoding="utf-8"
        )
        if args.plots:
            plots(args.output, rows, series)
    print(
        json.dumps(
            {
                "complete": True,
                "attempts": len(rows),
                "totals": stats["totals"],
                "original_manifest_entries_verified": stats["original_manifest_entries_verified"],
                "load_executed": False,
            }
        )
    )


if __name__ == "__main__":
    main()
