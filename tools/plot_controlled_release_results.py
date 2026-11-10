"""Plot audited controlled-release outcomes with explicit denominators."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def fraction(rows, outcome, eligible=None):
    valid = [r for r in rows if r["evaluation_valid"]
             and (eligible is None or r["eligible"] == eligible)]
    return {"numerator": sum(bool(r[outcome]) for r in valid),
            "denominator": len(valid),
            "valid_assessments": sum(r["evaluation_valid"] for r in rows),
            "planned_assessments": len(rows),
            "execution_failures": sum(not r["evaluation_valid"] for r in rows)}


def summarize(audit):
    if audit["scored_units"] != audit["planned_units"] or audit["missing_units"]:
        raise ValueError("Plot only after every planned unit has a terminal record.")
    rows = audit["rows"]
    component, loops = {}, {}
    for arm in "ABC":
        subset = [r for r in rows if r["kind"] == "component" and r["controller"] == arm]
        component[arm] = {
            "false_release": fraction(subset, "false_release", False),
            "eligible_release": fraction(subset, "released", True),
            "false_rejection": fraction(subset, "false_rejection", True),
        }
    for condition in ("T0", "T5"):
        loops[condition] = {}
        for arm in ("A", "C"):
            subset = [r for r in rows if r["kind"] == "workflow"
                      and r["condition"] == condition and r["controller"] == arm]
            loops[condition][arm] = {
                "task_completion_with_release": fraction(subset, "released_task_success"),
                "released_safe_narrowing": fraction(subset, "released_safe_narrowing"),
                "actual_repair": fraction(subset, "actual_repair"),
                "initially_ineligible": sum(r["first_artifact_eligible"] is False for r in subset),
                "round_counts": dict(Counter(str(r["rounds"]) for r in subset)),
                "final_modes": dict(Counter(r["final_mode"] for r in subset)),
            }
    return {"phase": audit["phase"], "planned_units": audit["planned_units"],
            "component": component, "generation": loops,
            "api_events": audit["api_events"], "response_models": audit["response_models"],
            "recorded_tokens": audit["recorded_tokens_all_traces"]}


def count_text(value):
    return str(value["numerator"]) + "/" + str(value["denominator"])


def export(audit_file, output):
    if output.exists():
        raise FileExistsError("Use a new output directory; previous reports are preserved.")
    audit = json.loads(audit_file.read_text(encoding="utf-8"))
    data = summarize(audit)
    output.mkdir(parents=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    matplotlib.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "axes.spines.top": False, "axes.spines.right": False,
        "pdf.fonttype": 42, "svg.fonttype": "none",
    })
    colors = {"A": "#48668C", "B": "#7A7A7A", "C": "#218C74"}
    figure, axes = plt.subplots(2, 2, figsize=(10.6, 6.8))

    def panel(axis, title, values):
        labels = list(values)
        for y, arm in enumerate(labels):
            record = values[arm]
            n, denominator = record["numerator"], record["denominator"]
            value = n / denominator * 100 if denominator else 0
            axis.barh(y, value, height=0.48, color=colors[arm])
            axis.text(103, y, count_text(record) if denominator else "NA (0 valid)",
                      va="center", fontsize=10)
            if not denominator:
                axis.plot(0, y, marker="x", color=colors[arm])
        axis.set(yticks=range(len(labels)), yticklabels=labels, xlim=(0, 125),
                 xticks=(0, 25, 50, 75, 100), xlabel="Percent of stated denominator")
        axis.invert_yaxis()
        axis.set_title(title, loc="left", fontsize=11, pad=12)
        axis.set_axisbelow(True)
        axis.grid(axis="x", alpha=0.2)

    panel(axes[0, 0], "(a) Component: false release",
          {a: d["false_release"] for a, d in data["component"].items()})
    panel(axes[0, 1], "(b) Component: eligible release",
          {a: d["eligible_release"] for a, d in data["component"].items()})
    panel(axes[1, 0], "(c) Clean loops: released numeric result",
          {a: d["task_completion_with_release"] for a, d in data["generation"]["T0"].items()})
    panel(axes[1, 1], "(d) Missing-evidence loops: safe narrowing",
          {a: d["released_safe_narrowing"] for a, d in data["generation"]["T5"].items()})
    figure.suptitle("Controlled release evaluation: " + data["phase"], fontsize=13, y=0.98)
    figure.text(0.06, 0.018,
                "Counts are descriptive. Repeats are not independent tasks. "
                "Safe narrowing does not complete the numeric task.", fontsize=9)
    figure.tight_layout(rect=(0, 0.05, 1, 0.95), h_pad=2.4, w_pad=2.2)
    for suffix in ("png", "pdf", "svg"):
        figure.savefig(output / ("controlled_release." + suffix), dpi=220)
    plt.close(figure)

    caption = (
        "# Figure caption\n\n"
        "Controlled release outcomes in the " + data["phase"] + " evaluation. "
        "(a) False releases among valid ineligible component assessments. "
        "(b) Releases among valid eligible component assessments. "
        "(c) Released numerical task completion among valid T0 generation runs. "
        "(d) Released safe narrowing among valid T5 generation runs. "
        "Labels show numerator/denominator. A is the existing controller; B "
        "unconditionally withholds A's validated outputs; C adds grounded "
        "verification. B is evaluated only in the component comparison. "
        "Execution failures are excluded from valid-outcome denominators and "
        "retained separately in the tables. The component inputs share fixed "
        "review scores across arms. Synthetic tasks, conditions and repeated "
        "calls do not constitute independent scientific questions. Safe narrowing "
        "means an eligible statement of missing or conflicting evidence; it does "
        "not complete the original numerical task. Initial artifact eligibility "
        "and actual repair are reported separately. No inferential interval or "
        "significance claim is attached to these descriptive counts.\n"
    )
    lines = [
        "# Controlled Release Outcome Summary", "",
        "Phase: " + data["phase"] + ". All " + str(data["planned_units"]) +
        " planned units have terminal records.", "",
        "## Component comparison", "",
        "| Controller | False release / ineligible | Release / eligible | False rejection / eligible | Valid / planned assessments | Failures |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for arm, record in data["component"].items():
        base = record["false_release"]
        lines.append("| " + " | ".join((
            arm, count_text(base), count_text(record["eligible_release"]),
            count_text(record["false_rejection"]),
            str(base["valid_assessments"]) + "/" + str(base["planned_assessments"]),
            str(base["execution_failures"]))) + " |")
    lines += ["", "## Controlled generation", "",
              "| Condition | Controller | Released numeric result / valid | Released safe narrowing / valid | Initially ineligible | Repairs / valid | Valid / planned | Failures |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for condition, arms in data["generation"].items():
        for arm, record in arms.items():
            base = record["task_completion_with_release"]
            lines.append("| " + " | ".join((
                condition, arm, count_text(base), count_text(record["released_safe_narrowing"]),
                str(record["initially_ineligible"]), count_text(record["actual_repair"]),
                str(base["valid_assessments"]) + "/" + str(base["planned_assessments"]),
                str(base["execution_failures"]))) + " |")
    lines += ["", "Component and generation denominators are separate. Zero observed errors "
              "in this small synthetic set is not a guarantee of universal correctness.", "",
              "An initially eligible artifact cannot demonstrate controller-induced repair. "
              "Failure to release an eligible final artifact remains a false rejection.", "",
              "API events: `" + json.dumps(data["api_events"]) + "`.",
              "Returned model IDs: `" + json.dumps(data["response_models"]) + "`.",
              "Recorded tokens: `" + json.dumps(data["recorded_tokens"]) + "`.", ""]
    data["source_audit_sha256"] = hashlib.sha256(audit_file.read_bytes()).hexdigest()
    for name, text in (("REPORT.md", "\n".join(lines)), ("FIGURE_CAPTION.md", caption),
                       ("summary.json", json.dumps(data, indent=2, ensure_ascii=False))):
        with (output / name).open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(json.dumps({"output": str(output), "phase": data["phase"],
                      "planned_units": data["planned_units"]}, ensure_ascii=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    export(Path(args.audit).resolve(), Path(args.output).resolve())


if __name__ == "__main__":
    main()
