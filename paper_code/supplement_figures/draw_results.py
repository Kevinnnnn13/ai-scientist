"""Descriptive figures from frozen records and existing statistical estimates."""

import numpy as np

from plot_style import (
    PALETTE, arrow, axes_at, canvas, line, marker, panel, rect, save_figure, text,
)


def clean_axis(ax, left=True, bottom=True):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines["left"].set_visible(left)
    ax.spines["bottom"].set_visible(bottom)
    ax.tick_params(labelsize=8.3)
    ax.set_axisbelow(True)


def figure3(data):
    height = 642
    fig, page = canvas(height)
    case = data["case"]
    panel(page, "a", "One proposal across seven review rounds", 12, 18)
    text(page, 498, 39, "math01 / F0 clean", ha="right", color="muted", size=8.3)
    text(page, 12, 60, "Prime-gap proposal", size=9.8, weight="bold")
    text(page, 12, 84, "Granville-type vs\nCramer-type models", size=9, color="muted")
    text(page, 12, 113, "Proposed comparison; untested", size=8.3, color="muted")
    for yy, label, color, shape in [(141, "Hypothesis", "blue", "o"), (163, "Evidence", "teal", "s")]:
        line(page, [(12, yy), (32, yy)], color, 1.6, dash=(0, (4, 2)) if shape == "s" else None)
        marker(page, 22, yy, shape, color, size=4.5, fill=True)
        text(page, 42, yy, label, size=8.8)
    text(page, 12, 188, "Stored best", size=8.3, color="muted")
    text(page, 105, 188, "72 / 74", size=9, weight="bold")
    text(page, 12, 208, "Terminal", size=8.3, color="muted")
    text(page, 105, 208, "70 / 84", size=9, weight="bold")

    plot_left, plot_width = 228, 241
    chart = axes_at(fig, height, plot_left, 56, plot_width, 141)
    rounds = [row["round"] for row in case["rounds"]]
    chart.plot(rounds, [r["hypothesis_score"] for r in case["rounds"]],
               color=PALETTE["blue"], marker="o", markersize=4.6, linewidth=1.5)
    chart.plot(rounds, [r["data_score"] for r in case["rounds"]],
               color=PALETTE["teal"], marker="s", markersize=4.4,
               linewidth=1.5, linestyle=(0, (4, 2)))
    chart.axhline(case["quality_target"], color=PALETTE["muted"], linestyle=(0, (2, 2)), linewidth=0.8)
    chart.text(1.04, 94.5, "Hypothesis target 90", fontsize=8.2, color=PALETTE["muted"])
    chart.annotate("84", (7, 84), xytext=(7, 1), textcoords="offset points", fontsize=8.5, color=PALETTE["dark_teal"])
    chart.annotate("70", (7, 70), xytext=(7, -3), textcoords="offset points", fontsize=8.5, color=PALETTE["blue"])
    chart.set(xlim=(0.75, 7.35), ylim=(0, 100), xticks=rounds,
              yticks=[0, 20, 40, 60, 80, 100], ylabel="Review score", xlabel="Review round")
    clean_axis(chart)

    panel(page, "b", "Issue-level review traces", 12, 247)
    text(page, 498, 247, "All ten recorded issues", ha="right", color="muted", size=8.3)
    marker(page, 16, 270, "o", "coral", size=4.8)
    text(page, 27, 270, "Active", size=8.3, color="muted")
    marker(page, 83, 270, "D", "teal", size=5.5, fill=True)
    text(page, 94, 270, "Resolved", size=8.3, color="muted")
    line(page, [(159, 270), (165, 270)], "light", 0.85)
    text(page, 175, 270, "Not recorded", size=8.3, color="muted")
    text(page, 498, 270, "Each trace uses the same 0-100 scale", ha="right", size=8.2, color="muted")
    xs = [plot_left + (r-0.75)/6.6*plot_width for r in rounds]
    text(page, 12, 296, "Issue", size=8.3, color="muted")
    for xx, rr in zip(xs, rounds):
        text(page, xx, 296, str(rr), ha="center", size=8.3, color="muted")
        line(page, [(xx, 308), (xx, 563)], "rule", 0.4)
    text(page, 497, 296, "Final", size=8.3, ha="center", color="muted")
    short_names = [
        "Granville parameterization", "Tree / source mismatch", "Sieve-loss definition",
        "Prime-table feasibility", "Alternative data plan", "Error-range derivation",
        "Incremental contribution", "Truncated hypothesis", "Tuple-count boundary",
        "Pairing / comparison count",
    ]
    row_step, amplitude = 25.3, 19.0
    for i, (issue, label) in enumerate(zip(case["issues"], short_names)):
        center_y = 322 + i*row_step
        text(page, 12, center_y, f'I{issue["id"]}', size=8.2, color="muted")
        text(page, 34, center_y, label, size=8.5)
        values = {entry["round"]: entry for entry in issue["history"]}
        trace = [(xs[rr-1], center_y + amplitude*(0.5-values[rr]["score"]/100))
                 for rr in rounds if rr in values]
        if len(trace) > 1:
            line(page, trace, "coral", 0.9)
        for j, state in enumerate(issue["statuses"]):
            if state == "not_recorded":
                line(page, [(xs[j]-2, center_y), (xs[j]+2, center_y)], "light", 0.8)
                continue
            entry = values[rounds[j]]
            assert entry["status"] == state
            yy = center_y + amplitude*(0.5-entry["score"]/100)
            if state == "active":
                marker(page, xs[j], yy, "o", "coral", size=4.3)
            elif state == "resolved":
                marker(page, xs[j], yy, "D", "teal", size=5.5, fill=True)
            else:
                raise ValueError(state)
        final = issue["history"][-1]
        text(page, 497, center_y, str(final["score"]), size=8.5, ha="center",
             color="dark_teal" if final["status"] == "resolved" else "ink")
    line(page, [(12, 575), (498, 575)], "rule", 0.75)
    for xx, label, value in [(12, "Terminal status", "in_progress"),
                              (184, "Issue ledger", "9 active / 1 resolved"),
                              (365, "Tree / retrieval", "v1 / 4 counted")]:
        text(page, xx, 590, label, size=8.3, color="muted")
        text(page, xx, 608, value, size=9.3, weight="bold")
    text(page, 12, 627, "Search exhausted. I8-I10 first recorded in round 6; I10 resolved in round 7.", size=8.2, color="muted")
    return save_figure(fig, "figure3_real_run_case", height)


def state_mark(ax, x, y, state, size=6.4):
    if state == "validated":
        marker(ax, x, y, "o", "blue", size=size, fill=True)
    elif state == "in_progress":
        marker(ax, x, y, "s", "muted", size=size-0.5)
    elif state == "ungated":
        line(ax, [(x-3, y), (x+3, y)], "muted", 1)
    else:
        raise ValueError(state)


def figure4(data):
    height = 603
    fig, ax = canvas(height)
    panel(ax, "a", "Release states across the pilot", 12, 18)
    text(ax, 498, 18, "72 runs / one per cell", ha="right", color="muted", size=8.3)
    for xx, label, state in [(17, "Ungated (6; gate N/A)", "ungated"),
                              (208, "in_progress (53)", "in_progress"),
                              (377, "validated (13)", "validated")]:
        state_mark(ax, xx, 44, state)
        text(ax, xx+12, 44, label, size=8.5, color="muted")
    columns = [253, 293, 348, 388, 443, 483]
    for xx, label, color in [(273, "Chemistry", "blue"), (368, "Finance", "teal"), (463, "Mathematics", "muted")]:
        text(ax, xx, 72, label, size=8.7, ha="center", weight="bold")
        line(ax, [(xx-34, 81), (xx+34, 81)], color, 1.6)
    for xx, question in zip(columns, data["questions"]):
        text(ax, xx, 94, question, size=8.2, ha="center", color="muted")
    cells = {(r["condition_id"], r["question_id"]): r["plan_status"] for r in data["pilot"]}
    rect(ax, 8, 287, 490, 38, face="blue_tint", edge="blue_tint", lw=0, zorder=0)
    for i, condition in enumerate(data["conditions"]):
        yy = 117 + i*18
        override = i >= 10
        text(ax, 12, yy, condition["label_en"], size=8.7, weight="bold" if override else "normal")
        for xx, question in zip(columns, data["questions"]):
            state_mark(ax, xx, yy, cells[(condition["id"], question)], size=7)
        if i in [0, 1, 9]:
            line(ax, [(12, yy+9), (498, yy+9)], "rule", 0.55)
    for xx in [320, 416]:
        line(ax, [(xx, 106), (xx, 325)], "rule", 0.55)
    line(ax, [(12, 340), (498, 340)], "rule", 0.75)

    panel(ax, "b", "A separate blocking intervention", 12, 360)
    text(ax, 498, 360, "Six matched reruns", ha="right", size=8.3, color="muted")
    for xx, top, lower in [(160, "Original", "validated"), (285, "Guarded", "in_progress"),
                            (392, "Hypothesis", "before / after"), (474, "Evidence", "before / after")]:
        text(ax, xx, 386, top, size=8.6, ha="center", weight="bold")
        text(ax, xx, 402, lower, size=8.2, ha="center", color="muted")
    for i, row in enumerate(data["repair_pairs"]):
        yy = 424 + i*21
        text(ax, 12, yy, row["question_id"], size=8.7)
        state_mark(ax, 160, yy, row["before_status"], size=7)
        arrow(ax, (172, yy), (271, yy), color="light", lw=0.9, scale=7.5)
        state_mark(ax, 285, yy, row["after_status"], size=7)
        text(ax, 392, yy, f'{row["before_score"]:g} / {row["after_score"]:g}', ha="center", size=8.7)
        text(ax, 474, yy, f'{row["before_data_score"]:g} / {row["after_data_score"]:g}', ha="center", size=8.7)
    text(ax, 12, 555, "State changed; hypothesis and evidence scores did not.", size=9.1, weight="bold")
    text(ax, 12, 575, "Guard blocks every validated state; these six reruns are separate from the pilot.", size=8.2, color="muted")
    text(ax, 12, 592, "All six terminal states were saved before a score-plot write failure.", size=8.2, color="muted")
    return save_figure(fig, "figure4_faults_and_repair", height)


def format_bound(value):
    return f"{value:g}" if float(value).is_integer() else f"{value:.1f}"


def figure5(data):
    height = 494
    fig, page = canvas(height)
    panel(page, "a", "Paired reader ratings", 12, 18)
    text(page, 498, 18, "Exploratory / n = 20", ha="right", size=8.3, color="muted")
    text(page, 12, 42, "Processed minus unprocessed", size=8.6, color="muted")
    text(page, 397, 65, "Mean [95% CI]", size=8.4, ha="center", weight="bold")
    text(page, 478, 65, "Holm P", size=8.4, ha="center", weight="bold")
    chart = axes_at(fig, height, 152, 80, 186, 155)
    means = np.array([r["mean_diff"] for r in data["ratings"]])
    lower = np.array([r["ci95_low"] for r in data["ratings"]])
    upper = np.array([r["ci95_high"] for r in data["ratings"]])
    chart.errorbar(means, np.arange(5), xerr=[means-lower, upper-means], fmt="o",
                   color=PALETTE["blue"], markersize=5.8, capsize=3,
                   elinewidth=1.2, capthick=1.1, markeredgewidth=0.7, markeredgecolor="white")
    chart.axvline(0, linestyle=(0, (3, 2)), linewidth=0.85, color=PALETTE["muted"])
    chart.set(xlim=(-10, 20), ylim=(4.5, -0.5), xticks=[-10, 0, 10, 20], yticks=[],
              xlabel="Difference (score points)")
    clean_axis(chart, left=False)
    for i, row in enumerate(data["ratings"]):
        yy = 95.5 + i*31
        text(page, 12, yy, row["label_en"], size=8.7)
        estimate = f'{row["mean_diff"]:+g} [{format_bound(row["ci95_low"])}, {format_bound(row["ci95_high"])}]'
        text(page, 397, yy, estimate, size=8.6, ha="center")
        text(page, 478, yy, f'{row["p_holm"]:.3f}', size=8.6, ha="center")
    text(page, 12, 277, "Unadjusted intervals; no rating item meets the Holm-adjusted 0.05 threshold.", size=8.2, color="muted")
    line(page, [(12, 293), (498, 293)], "rule", 0.75)

    panel(page, "b", "Forced-choice preference", 12, 314)
    rect(page, 153, 333, 9, 7, face="teal", edge="teal", lw=0)
    text(page, 170, 337, "Processed", size=8.3, color="muted")
    patch = rect(page, 270, 333, 9, 7, face="wash", edge="light", lw=0.5)
    patch.set_hatch("////")
    text(page, 287, 337, "Unprocessed", size=8.3, color="muted")
    text(page, 478, 337, "Holm P", size=8.4, ha="center", weight="bold")
    chart = axes_at(fig, height, 152, 355, 270, 84)
    processed = np.array([r["processed"] for r in data["preferences"]])
    unprocessed = np.array([r["unprocessed"] for r in data["preferences"]])
    chart.axvline(10, color=PALETTE["muted"], linestyle=(0, (2, 2)), linewidth=0.8, zorder=0)
    chart.barh(np.arange(3), processed, height=0.48, color=PALETTE["teal"], zorder=2)
    chart.barh(np.arange(3), unprocessed, left=processed, height=0.48,
               color=PALETTE["wash"], edgecolor=PALETTE["light"], linewidth=0.5, hatch="////", zorder=2)
    for i, row in enumerate(data["preferences"]):
        yy = 369 + i*28
        text(page, 12, yy, row["label_en"], size=8.7)
        chart.text(processed[i]/2, i, str(processed[i]), fontsize=8.6, ha="center", va="center",
                   color="#121A20", fontweight="bold")
        chart.text(processed[i]+unprocessed[i]/2, i, str(unprocessed[i]), fontsize=8.6,
                   ha="center", va="center", color=PALETTE["ink"], fontweight="bold",
                   bbox={"facecolor": PALETTE["wash"], "edgecolor": "none", "pad": 1})
        text(page, 478, yy, f'{row["p_holm"]:.3f}', ha="center", size=8.6,
             weight="bold" if row["significant_holm_0_05"] else "normal")
    chart.set(xlim=(0, 20), ylim=(2.5, -0.5), xticks=[0, 5, 10, 15, 20], yticks=[])
    clean_axis(chart, left=False)
    text(page, 287, 464, "Participants (20 per item); dotted line = equal preference", ha="center", size=8.2, color="muted")
    text(page, 12, 480, "Constructed document pairs; unprocessed always read first.", size=8.2, color="muted")
    return save_figure(fig, "figure5_reader_evaluation", height)
