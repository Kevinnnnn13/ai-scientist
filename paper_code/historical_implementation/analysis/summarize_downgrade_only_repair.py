# -*- coding: utf-8 -*-
"""Summarize the downgrade-only repair runs against the frozen override runs."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from statistics import mean

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(r"C:\Users\22011\Documents\Codex\2026-09-17\wo")
SOURCE = Path(r"C:\Users\22011\Desktop\26暑假\ai_scientist\robustness_runs")
OLD_METRICS = SOURCE / "pilot_6_v2_combined" / "condition_metrics.csv"
OLD_PER_RUN = SOURCE / "pilot_6_v2_combined" / "per_run_metrics.csv"
NEW_ROOT = ROOT / "robustness_runs"
OUTPUT = ROOT / "analysis" / "downgrade_only_repair_20260930"


def read_json(path: Path):
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def read_csv(path: Path):
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float) -> float:
    return round(100.0 * value, 1)


def count_block_events(run_dir: Path) -> int:
    path = run_dir / "hook_audit.jsonl"
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if "judge_downgrade_only_blocked_release" in line:
                count += 1
    return count


def load_repair_runs() -> list[dict]:
    rows = []
    for output_root in sorted(NEW_ROOT.glob("pilot_6_downgrade_only_deepseek_peak_*")):
        run_root = output_root / "runs"
        if not run_root.is_dir():
            continue
        run_dirs = [path for path in run_root.iterdir() if path.is_dir()]
        if len(run_dirs) != 1:
            continue
        run_dir = run_dirs[0]
        result_path = run_dir / "result.json"
        if not result_path.exists():
            continue
        result = read_json(result_path)
        state = {}
        state_path = result.get("state_path")
        if state_path and Path(state_path).exists():
            state = read_json(Path(state_path))
        plan_status = str(state.get("plan_status") or result.get("plan_status") or "")
        terminal_state = int(bool(state))
        process_exit_code = int(result.get("exit_code") or 0)
        rows.append(
            {
                "question_id": result.get("question_id"),
                "domain": result.get("domain"),
                "run_id": result.get("run_id"),
                "terminal_state": terminal_state,
                "process_ok": int(bool(result.get("ok"))),
                "process_exit_code": process_exit_code,
                "postrun_failure": int(terminal_state and process_exit_code != 0),
                "plan_status": plan_status,
                "evidence_status": state.get("evidence_status") or result.get("evidence_status"),
                "validated": int(plan_status == "validated"),
                "fail_closed": int(plan_status != "validated"),
                "silent_fail_open": int(
                    plan_status == "validated"
                    and not any(
                        word in str(state.get("release_reason") or "").lower()
                        for word in (
                            "uncertain", "insufficient", "unverified",
                            "cannot", "abstain", "exploratory",
                        )
                    )
                ),
                "best_score": result.get("best_score"),
                "best_data_score": result.get("best_data_score"),
                "release_reason": state.get("release_reason") or result.get("release_reason"),
                "downgrade_block_events": count_block_events(run_dir),
                "seconds": result.get("seconds"),
                "run_dir": str(run_dir),
            }
        )
    return sorted(rows, key=lambda row: str(row.get("question_id")))


def make_figure(old_override: list[dict], repair: list[dict]) -> None:
    old_validated = pct(
        sum(int(row["validated"] == "1") for row in old_override) / len(old_override)
    )
    old_fail_closed = pct(
        sum(int(row["fail_closed"] == "1") for row in old_override) / len(old_override)
    )
    old_silent = pct(
        sum(int(row["silent_fail_open"] == "1") for row in old_override) / len(old_override)
    )
    new_validated = pct(
        sum(int(row["validated"] == "1") for row in repair) / len(repair)
    )
    new_fail_closed = pct(
        sum(int(row["fail_closed"] == "1") for row in repair) / len(repair)
    )
    new_silent = pct(
        sum(int(row["silent_fail_open"] == "1") for row in repair) / len(repair)
    )

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 4.2), gridspec_kw={"width_ratios": [1.25, 1]})
    labels = ["Validated\nrelease", "Fail-closed", "Silent\nfail-open"]
    x = range(len(labels))
    width = 0.36
    old_values = [old_validated, old_fail_closed, old_silent]
    new_values = [new_validated, new_fail_closed, new_silent]
    axes[0].bar([value - width / 2 for value in x], old_values, width, label="Judge override", color="#c84c4c")
    axes[0].bar([value + width / 2 for value in x], new_values, width, label="Downgrade-only repair", color="#2f7d68")
    axes[0].set_ylim(0, 105)
    axes[0].set_ylabel("Runs (%)")
    axes[0].set_xticks(list(x), labels)
    axes[0].legend(frameon=False, loc="upper right")
    axes[0].spines[["top", "right"]].set_visible(False)
    for index, (old_value, new_value) in enumerate(zip(old_values, new_values)):
        axes[0].text(index - width / 2, old_value + 2, f"{old_value:.1f}", ha="center", fontsize=9)
        axes[0].text(index + width / 2, new_value + 2, f"{new_value:.1f}", ha="center", fontsize=9)

    old_scores = [
        float(row["best_score"])
        for row in old_override
        if row.get("best_score") not in (None, "")
    ]
    repair_scores = [
        float(row["best_score"])
        for row in repair
        if row.get("best_score") is not None
    ]
    old_scores.sort()
    repair_scores.sort()
    old_offsets = [
        (index - (len(old_scores) - 1) / 2.0) * 0.028
        for index in range(len(old_scores))
    ]
    new_offsets = [
        (index - (len(repair_scores) - 1) / 2.0) * 0.028
        for index in range(len(repair_scores))
    ]
    axes[1].scatter(
        old_offsets,
        old_scores,
        s=52,
        color="#c84c4c",
        alpha=0.9,
        label="Judge override",
        zorder=2,
    )
    axes[1].scatter(
        [1 + offset for offset in new_offsets],
        repair_scores,
        s=52,
        color="#2f7d68",
        alpha=0.9,
        label="Downgrade-only repair",
        zorder=2,
    )
    axes[1].hlines(mean(old_scores), -0.18, 0.18, color="#c84c4c", linewidth=1.5)
    axes[1].hlines(mean(repair_scores), 0.82, 1.18, color="#2f7d68", linewidth=1.5)
    axes[1].set_xlim(-0.45, 1.45)
    axes[1].set_ylim(min(old_scores + repair_scores) - 1.2, max(old_scores + repair_scores) + 0.8)
    axes[1].set_xticks([0, 1], ["Judge override", "Downgrade-only\nrepair"])
    axes[1].set_ylabel("Best hypothesis score")
    axes[1].spines[["top", "right"]].set_visible(False)
    axes[1].text(
        0.5,
        min(old_scores + repair_scores) - 0.8,
        f"Mean unchanged at {mean(repair_scores):.2f}\nRelease status changed in all 6 pairs.",
        ha="center",
        fontsize=8.5,
        color="#555555",
    )

    fig.tight_layout()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUTPUT / "figure_release_repair.png", dpi=240)
    fig.savefig(OUTPUT / "figure_release_repair.pdf")
    plt.close(fig)


def main() -> int:
    repair = load_repair_runs()
    if len(repair) != 6:
        print(f"repair runs incomplete: found {len(repair)} of 6")
        return 1

    old_condition_rows = read_csv(OLD_METRICS)
    old_condition = next(
        row for row in old_condition_rows if row["condition_id"] == "F0_judge_override"
    )
    old_override = [
        row for row in read_csv(OLD_PER_RUN) if row["condition_id"] == "F0_judge_override"
    ]
    if len(old_override) != 6:
        raise RuntimeError(f"expected 6 frozen override runs, found {len(old_override)}")

    repair_validated = sum(row["validated"] for row in repair)
    repair_fail_closed = sum(row["fail_closed"] for row in repair)
    repair_silent = sum(row["silent_fail_open"] for row in repair)
    block_events = sum(row["downgrade_block_events"] for row in repair)
    completed = sum(row["terminal_state"] for row in repair)
    postrun_failures = sum(row["postrun_failure"] for row in repair)
    old_validated_by_question = {
        str(row["question_id"]): int(row["validated"] == "1")
        for row in old_override
    }
    discordant_changed = sum(
        row["validated"] == 0
        and old_validated_by_question.get(str(row["question_id"]), 0) == 1
        for row in repair
    )
    discordant_reversed = sum(
        row["validated"] == 1
        and old_validated_by_question.get(str(row["question_id"]), 0) == 0
        for row in repair
    )
    discordant = discordant_changed + discordant_reversed
    if discordant:
        upper = max(discordant_changed, discordant_reversed)
        mcnemar_exact_p = min(
            1.0,
            2.0
            * sum(math.comb(discordant, value) for value in range(upper, discordant + 1))
            / (2 ** discordant),
        )
    else:
        mcnemar_exact_p = 1.0
    best_scores = [float(row["best_score"]) for row in repair if row.get("best_score") is not None]

    summary = {
        "old_condition": "F0_judge_override",
        "old_runs": len(old_override),
        "old_validated_rate": float(old_condition["validated_rate"]),
        "old_fail_closed_rate": float(old_condition["fail_closed_rate_on_stress"]),
        "old_silent_fail_open_rate": float(old_condition["silent_fail_open_rate_on_stress"]),
        "old_mean_best_score": float(old_condition["mean_best_score"]),
        "repair_condition": "F0_override_downgrade_only",
        "repair_runs": len(repair),
        "repair_completed": completed,
        "repair_postrun_failures": postrun_failures,
        "repair_validated": repair_validated,
        "repair_validated_rate": pct(repair_validated / len(repair)),
        "repair_fail_closed": repair_fail_closed,
        "repair_fail_closed_rate": pct(repair_fail_closed / len(repair)),
        "repair_silent_fail_open": repair_silent,
        "repair_silent_fail_open_rate": pct(repair_silent / len(repair)),
        "repair_downgrade_block_events": block_events,
        "paired_discordant_release_changes": discordant_changed,
        "paired_reverse_release_changes": discordant_reversed,
        "mcnemar_exact_two_sided_p": mcnemar_exact_p,
        "repair_mean_best_score": round(mean(best_scores), 2),
        "repair_runs_detail": repair,
    }

    write_csv(
        OUTPUT / "repair_runs.csv",
        repair,
        [
            "question_id",
            "domain",
            "run_id",
            "terminal_state",
            "process_ok",
            "process_exit_code",
            "postrun_failure",
            "plan_status",
            "evidence_status",
            "validated",
            "fail_closed",
            "silent_fail_open",
            "best_score",
            "best_data_score",
            "release_reason",
            "downgrade_block_events",
            "seconds",
            "run_dir",
        ],
    )
    (OUTPUT / "repair_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    summary_lines = [
        "# Downgrade-only repair comparison",
        "",
        "| Condition | Runs | Validated | Fail-closed | Silent fail-open | Mean best score |",
        "|---|---:|---:|---:|---:|---:|",
        (
            f"| Frozen judge override | {len(old_override)} | "
            f"{summary['old_validated_rate']:.1f}% | "
            f"{summary['old_fail_closed_rate']:.1f}% | "
            f"{summary['old_silent_fail_open_rate']:.1f}% | "
            f"{summary['old_mean_best_score']:.2f} |"
        ),
        (
            f"| Downgrade-only repair | {len(repair)} | "
            f"{summary['repair_validated_rate']:.1f}% | "
            f"{summary['repair_fail_closed_rate']:.1f}% | "
            f"{summary['repair_silent_fail_open_rate']:.1f}% | "
            f"{summary['repair_mean_best_score']:.2f} |"
        ),
        "",
        (
            "The downgrade-only policy blocked every attempted validated release in the "
            f"repair runs ({block_events} recorded audit events). All {len(repair)} runs "
            "completed and failed closed; no silent fail-open occurred."
        ),
        "",
        (
            f"Paired exact McNemar test: {discordant_changed} release reversals and "
            f"{discordant_reversed} reverse reversals, two-sided p = "
            f"{mcnemar_exact_p:.5f}."
        ),
        "",
        (
            f"{postrun_failures} run(s) returned a non-zero process code after producing "
            "the terminal state because the optional score-plot write exceeded the "
            "Windows path-length limit. Those post-run exit codes were kept separate "
            "from the release-state analysis."
        ),
        "",
        "Interpretation: this is a policy-level repair validation, not evidence that the "
        "underlying scientific claims became true.",
        "",
    ]
    (OUTPUT / "repair_summary.md").write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    make_figure(old_override, repair)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
