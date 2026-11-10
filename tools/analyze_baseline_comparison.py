# -*- coding: utf-8 -*-
"""Summarize clean F0 versus the flat-RAG baseline.

This comparison describes observable behavior only. It does not estimate
scientific correctness because the baseline does not pass through the same
release gate or scoring loop.
"""

import argparse
import csv
import statistics
from collections import Counter
from pathlib import Path


CONDITIONS = ("F0_clean", "B1_flat_rag_clean")


def _number(row, field, default=0.0):
    value = row.get(field, "")
    if value in ("", None):
        return default
    return float(value)


def _summarize(rows, condition, domain):
    selected = [
        row for row in rows
        if row["condition_id"] == condition
        and (domain == "all" or row["domain"] == domain)
    ]
    if not selected:
        return None

    status_counts = Counter(row["plan_status"] for row in selected)
    costs = [
        float(row["api_cost_cny"])
        for row in selected
        if row.get("api_cost_cny", "") not in ("", None)
    ]
    score_values = [
        float(row["best_score"])
        for row in selected
        if row.get("best_score", "") not in ("", None)
    ]
    data_score_values = [
        float(row["best_data_score"])
        for row in selected
        if row.get("best_data_score", "") not in ("", None)
    ]
    return {
        "condition_id": condition,
        "domain": domain,
        "runs": len(selected),
        "validated_count": sum(row["validated"] == "1" for row in selected),
        "released_count": sum(row["released"] == "1" for row in selected),
        "nonrelease_count": sum(row["released"] != "1" for row in selected),
        "mean_best_score": round(statistics.mean(score_values), 2)
        if score_values else None,
        "mean_best_data_score": round(statistics.mean(data_score_values), 2)
        if data_score_values else None,
        "mean_citation_traceability": round(
            statistics.mean(
                _number(row, "citation_traceability") for row in selected
            ),
            3,
        ),
        "mean_literature_count": round(
            statistics.mean(_number(row, "literature_count") for row in selected),
            2,
        ),
        "mean_output_chars": round(
            statistics.mean(_number(row, "output_chars") for row in selected),
            1,
        ),
        "mean_seconds": round(
            statistics.mean(_number(row, "seconds") for row in selected),
            1,
        ),
        "recorded_cost_cny": round(sum(costs), 4) if costs else None,
        "cost_missing_runs": len(selected) - len(costs),
        "plan_status_counts": "; ".join(
            f"{status}:{count}" for status, count in sorted(status_counts.items())
        ),
    }


def build(metrics_csv, output_dir):
    with metrics_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    domains = ["all"] + sorted({
        row["domain"] for row in rows if row["condition_id"] in CONDITIONS
    })
    summaries = []
    for domain in domains:
        for condition in CONDITIONS:
            summary = _summarize(rows, condition, domain)
            if summary:
                summaries.append(summary)

    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "baseline_comparison.csv"
    fields = list(summaries[0].keys())
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(summaries)

    lines = [
        "# Clean F0 versus Flat-RAG baseline",
        "",
        "This table compares observable run behavior. B1 is an ungated baseline: "
        "it did not pass through the review loop or release gate, so its "
        "`released_count` is not an accuracy or scientific-correctness score.",
        "",
        "| Domain | Condition | n | Validated | Released | Mean score | Mean data score | "
        "Citation traceability | Literature count | Output chars | Seconds | "
        "Recorded cost (CNY) | Missing cost records |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(value, digits=2):
        return "N/A" if value is None else f"{value:.{digits}f}"

    for row in summaries:
        lines.append(
            f"| {row['domain']} | {row['condition_id']} | {row['runs']} | "
            f"{row['validated_count']} | {row['released_count']} | "
            f"{fmt(row['mean_best_score'])} | {fmt(row['mean_best_data_score'])} | "
            f"{row['mean_citation_traceability']:.3f} | "
            f"{row['mean_literature_count']:.2f} | {row['mean_output_chars']:.1f} | "
            f"{row['mean_seconds']:.1f} | "
            f"{fmt(row['recorded_cost_cny'], 4)} | "
            f"{row['cost_missing_runs']} |"
        )

    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "- F0 clean produced no validated releases in this pilot.",
        "- B1 always released because it has no gate; this cannot be interpreted "
        "as better scientific quality.",
        "- Citation traceability is computed from different output structures and "
        "is not a shared accuracy metric.",
        "- The missing B1 cost records must not be reported as zero cost.",
        "- A shared human-audited rubric is still required to compare output quality.",
        "",
    ])
    markdown_path = output_dir / "baseline_comparison.md"
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, markdown_path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    csv_path, markdown_path = build(args.metrics.resolve(), args.out.resolve())
    print(csv_path)
    print(markdown_path)


if __name__ == "__main__":
    main()
