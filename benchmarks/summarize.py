"""Aggregate a complete benchmark run into reproducible CSV tables."""

import argparse
import csv
from collections import Counter
from math import ceil
from pathlib import Path
from statistics import median

from .run import BUDGETS, METHODS, json_lines


def ratio(numerator, denominator):
    return round(numerator / denominator, 6) if denominator else None


def p95(values):
    values = sorted(values)
    return round(values[ceil(0.95 * len(values)) - 1], 3) if values else None


def p50(values):
    return round(median(values), 3) if values else None


def write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def summarize_answers(rows, cases):
    roles = sorted({case["role"] for case in cases.values()})
    summary = []
    for method in METHODS:
        for role in ("all", *roles):
            selected = [row for row in rows if row["method"] == method and
                        (role == "all" or row["role"] == role)]
            good = [row for row in selected if row["status"] in {"answered", "insufficient_evidence"}]
            abstained = [row for row in good if row["status"] == "insufficient_evidence"]
            positive = [row for row in selected if cases[row["case_id"]]["expected"] == "answered"]
            negative = [row for row in selected if cases[row["case_id"]]["expected"] == "insufficient_evidence"]
            summary.append({
                "method": method, "role": role, "cases": len(selected),
                "answerable_cases": len(positive), "expected_abstentions": len(negative),
                "errors": len(selected) - len(good), "answered": len(good) - len(abstained),
                "authorized_recall_at_5": ratio(sum(row["recall_at_5"] for row in positive), len(positive)),
                "exact_answer_accuracy": ratio(sum(row["correct"] for row in selected), len(selected)),
                "answerable_accuracy": ratio(sum(row["correct"] for row in positive), len(positive)),
                "correct_abstention_rate": ratio(sum(row["correct"] for row in negative), len(negative)),
                "false_abstention_rate": ratio(
                    sum(row["status"] == "insufficient_evidence" for row in positive), len(positive),
                ),
                "context_leaks": sum(row["context_leak"] for row in selected),
                "citation_leaks": sum(row["citation_leak"] for row in selected),
                "restricted_fact_disclosures": sum(row["restricted_fact"] for row in selected),
                "passages": sum(len(row["passages"]) for row in good),
                "passage_support_rate": ratio(
                    sum(row["supported_passages"] for row in good), sum(len(row["passages"]) for row in good),
                ),
                "retrieval_p50_ms": p50([row["retrieval_ms"] for row in selected]),
                "retrieval_p95_ms": p95([row["retrieval_ms"] for row in selected]),
                "pipeline_p50_ms": p50([row["pipeline_ms"] for row in good]),
                "pipeline_p95_ms": p95([row["pipeline_ms"] for row in good]),
            })
    return summary


def summarize_sweep(rows, cases):
    roles = sorted({case["role"] for case in cases.values()})
    summary = []
    for role in ("all", *roles):
        subset = [row for row in rows if role == "all" or cases[row["case_id"]]["role"] == role]
        answerable = [row for row in subset if cases[row["case_id"]]["expected"] == "answered"]
        for budget in (None, *BUDGETS):
            def result(row):
                return row["pre_filter"] if budget is None else row["sweep"][str(budget)]
            summary.append({
                "strategy": "pre_filter" if budget is None else "post_filter",
                "candidate_budget": budget, "role": role, "cases": len(subset),
                "authorized_recall_at_5": ratio(
                    sum(cases[row["case_id"]]["target_id"] in result(row)["ids"] for row in answerable),
                    len(answerable),
                ),
                "five_sources_rate": ratio(sum(len(result(row)["ids"]) == 5 for row in subset), len(subset)),
                "mean_sources": round(sum(len(result(row)["ids"]) for row in subset) / len(subset), 3),
                "retrieval_p50_ms": p50([result(row)["retrieval_ms"] for row in subset]),
                "retrieval_p95_ms": p95([result(row)["retrieval_ms"] for row in subset]),
            })
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--cases", type=Path, default=Path("benchmarks/questions.jsonl"))
    args = parser.parse_args()
    cases = {row["case_id"]: row for row in json_lines(args.cases)}
    answers = json_lines(args.run / "answers.jsonl")
    retrievals = json_lines(args.run / "retrieval.jsonl")
    if Counter((row["case_id"], row["method"]) for row in answers) != {
        (case_id, method): 1 for case_id in cases for method in METHODS
    } or Counter(row["case_id"] for row in retrievals) != {case_id: 1 for case_id in cases}:
        parser.error("The run is incomplete or contains duplicate rows")
    summary = summarize_answers(answers, cases)
    write_csv(args.run / "summary.csv", summary)
    write_csv(args.run / "candidate_sweep.csv", summarize_sweep(retrievals, cases))
    for row in summary:
        if row["role"] == "all":
            print(row)


if __name__ == "__main__":
    main()
