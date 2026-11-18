"""Plot recall and Qdrant p95 from the candidate sweep table."""

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("table", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    with args.table.open(encoding="utf-8", newline="") as handle:
        overall = [row for row in csv.DictReader(handle) if row["role"] == "all"]
    pre = next(row for row in overall if row["strategy"] == "pre_filter")
    post = sorted((row for row in overall if row["strategy"] == "post_filter"),
                  key=lambda row: int(row["candidate_budget"]))
    budgets = [int(row["candidate_budget"]) for row in post]
    teal, orange, gray = "#155e75", "#a94708", "#475569"
    with plt.rc_context({"font.size": 10, "svg.fonttype": "none", "svg.hashsalt": "pfa-2026"}):
        figure, (recall, latency) = plt.subplots(1, 2, figsize=(9.7, 4.35), layout="constrained")
        for axis in (recall, latency):
            axis.set_xscale("log")
            axis.set_xticks(budgets, [str(budget) for budget in budgets])
            axis.set_xlabel("Candidats B (échelle logarithmique)")
            axis.grid(axis="y", alpha=0.25)
            axis.spines[["top", "right"]].set_visible(False)
        recall.plot(budgets, [100 * float(row["authorized_recall_at_5"]) for row in post],
                    "o-", color=teal, label="B · Recall@5 autorisé")
        recall.plot(budgets, [100 * float(row["five_sources_rate"]) for row in post],
                    "s-", color=orange, label="B · Cinq sources autorisées")
        recall.axhline(100 * float(pre["authorized_recall_at_5"]), linestyle="--",
                       color=gray, label="A · Les deux taux")
        recall.set(ylabel="Taux (%)", ylim=(0, 104), title="Rappel et couverture du contexte")
        latency.plot(budgets, [float(row["retrieval_p95_ms"]) for row in post],
                     "o-", color=teal, label="B · Après la recherche")
        latency.axhline(float(pre["retrieval_p95_ms"]), linestyle="--", color=gray,
                        label="A · Pendant la recherche")
        latency.set(ylabel="Latence p95 (ms)", ylim=(0, None), title="Temps de recherche dans Qdrant")
        for axis in (recall, latency):
            axis.legend(loc="upper center", bbox_to_anchor=(0.5, -0.25), frameon=False, fontsize=9)
        figure.suptitle(f"Effet du nombre de candidats · {pre['cases']} questions")
        figure.savefig(args.output, metadata={"Date": None} if args.output.suffix == ".svg" else None)
        plt.close(figure)

    if args.output.suffix == ".svg":
        lines = args.output.read_text(encoding="utf-8").splitlines()
        args.output.write_bytes(("\n".join(line.rstrip() for line in lines) + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
