"""Audit frozen outcomes and export descriptive results without model calls."""

import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from continue_controlled_study import check_saved_score, result_path
from run_programmatic_release import digest, read, write_new


def inspect(study):
    order = read(study / "run_order.json")
    envs = read(study / "private_environments.json")
    manifest = read(study / "manifest.json")
    rows, audits, missing = [], [], []
    models, api_statuses = Counter(), Counter()
    tokens = Counter()
    traces_seen = set()
    for item in order:
        scorefile = study / "scored" / (item["unit_id"] + ".json")
        if not scorefile.exists():
            missing.append(item["unit_id"])
            continue
        scored = read(scorefile)
        outcome_file = result_path(study, scored)
        result = read(outcome_file)
        if result.get("public_input_sha256"):
            check_saved_score(study, item, envs[item["case_id"]])
        if result["status"] == "completed" and not result.get("public_input_sha256"):
            raise ValueError("completed result lacks input binding")
        from programmatic_release_oracle import evaluate
        history = result.get("history", [])
        first_truth = evaluate(history[0]["artifact"], envs[item["case_id"]]) if history else None
        decision_arms = "ABC" if item["kind"] == "component" else (item["arm"],)
        for arm in decision_arms:
            score = scored["arms"].get(arm, {})
            decision = result.get("decisions", {}).get(arm, {})
            row = {
                "unit_id": item["unit_id"], "case_id": item["case_id"],
                "kind": item["kind"], "condition": item["case_id"].rsplit("_", 1)[1],
                "controller": arm, "repeat": item.get("repeat", ""),
                "status": scored["status"], "rounds": result.get("rounds", 0),
                "final_mode": (result.get("artifact") or {}).get("mode", ""),
                "eligible": score.get("eligible"),
                "released": score.get("released", False),
                "evaluation_valid": score.get("evaluation_valid", False),
                "false_release": score.get("false_release", False),
                "false_rejection": score.get("false_rejection", False),
                "released_task_success": score.get("released_task_success", False),
                "released_safe_narrowing": score.get("released_safe_narrowing", False),
                "first_artifact_eligible": first_truth["eligible"] if first_truth else None,
                "actual_repair": bool(first_truth and not first_truth["eligible"]
                                     and score.get("eligible")),
                "verification_calls": sum(
                    entry.get("decision", {}).get("evidence_check") != "not_evaluated"
                    and entry.get("decision", {}).get("verification_receipt") is not None
                    and not entry.get("decision", {}).get("cache_hit", False)
                    for entry in history
                ) if history else int(decision.get("verification_receipt") is not None),
                "release_errors": "|".join(decision.get("errors", [])),
                "oracle_errors": "|".join(scored["truth"]["errors"]),
                "result_path": outcome_file.relative_to(study).as_posix(),
            }
            rows.append(row)
        audits.append({"unit": item["unit_id"], "result_sha256": digest(outcome_file),
                       "oracle_recomputed": True})
    # Count all recorded responses, including failed/retried/partial attempts.
    for parent in (study / "runs", study / "attempts"):
        for trace in parent.rglob("api_trace.jsonl"):
            if trace in traces_seen:
                continue
            traces_seen.add(trace)
            for line in trace.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                api_statuses[event["status"]] += 1
                response = event.get("response", {})
                if response.get("model"):
                    models[response["model"]] += 1
                usage = response.get("usage") or {}
                for field in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    tokens[field] += usage.get(field, 0) or 0
    groups = defaultdict(Counter)
    for row in rows:
        group = groups[(row["kind"], row["condition"], row["controller"])]
        group["attempted"] += 1
        group["valid"] += row["evaluation_valid"]
        group["failure"] += not row["evaluation_valid"]
        if row["evaluation_valid"]:
            group["eligible"] += bool(row["eligible"])
            group["ineligible"] += not row["eligible"]
            group["released"] += row["released"]
            for field in ("false_release", "false_rejection", "released_task_success",
                          "released_safe_narrowing", "actual_repair"):
                group[field] += row[field]
    return {
        "phase": manifest["phase"], "planned_units": len(order),
        "scored_units": len(audits), "missing_units": missing, "rows": rows,
        "groups": [{"kind": key[0], "condition": key[1], "controller": key[2], **dict(value)}
                   for key, value in sorted(groups.items())],
        "audit": audits, "api_events": dict(api_statuses),
        "response_models": dict(models), "recorded_tokens_all_traces": dict(tokens),
        "unknown_usage": "Requests interrupted before a response may still be billed by the provider.",
    }


def export(study, output):
    if output.exists():
        raise FileExistsError("use a new report directory")
    data = inspect(study)
    output.mkdir(parents=True)
    write_new(output / "audit.json", data)
    if data["rows"]:
        with (output / "outcomes.csv").open("x", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data["rows"][0]))
            writer.writeheader()
            writer.writerows(data["rows"])
    lines = [
        "# Controlled Release Results", "",
        "Phase: " + data["phase"] + ".",
        f"Scored units: {data['scored_units']} / {data['planned_units']}.", "",
        "Counts are descriptive. Repeats and conditions are not independent research questions.",
        "A safe insufficient-evidence statement is not successful completion of the numeric task.", "",
        "| Type | Condition | Controller | Valid/attempted | Eligible | Released | False release | False rejection | Task success | Safe narrowing |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for group in data["groups"]:
        lines.append("| {kind} | {condition} | {controller} | {valid}/{attempted} | "
                     "{eligible} | {released} | {false_release} | {false_rejection} | "
                     "{released_task_success} | {released_safe_narrowing} |".format(
                         **{**{k: 0 for k in ("eligible", "released", "false_release", "false_rejection",
                                              "released_task_success", "released_safe_narrowing")},
                            **group}))
    lines += ["", "API events: `" + json.dumps(data["api_events"]) + "`.",
              "Returned model IDs: `" + json.dumps(data["response_models"]) + "`.",
              "Recorded tokens: `" + json.dumps(data["recorded_tokens_all_traces"]) + "`.",
              data["unknown_usage"], "",
              "Every recorded outcome was checked against its saved result hash and independently rescored.",
              "Missing units: `" + ", ".join(data["missing_units"]) + "`.", ""]
    with (output / "RESULTS.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines))
    print(json.dumps({k: data[k] for k in ("phase", "planned_units", "scored_units",
                                          "api_events", "response_models",
                                          "recorded_tokens_all_traces")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    export(Path(args.study).resolve(), Path(args.output).resolve())


if __name__ == "__main__":
    main()
