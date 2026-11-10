"""Offline baseline sensitivity using frozen results, without model calls."""

import argparse
import copy
import json
from pathlib import Path
import re

from audit_saved_release_decisions import legacy_functions
from continue_controlled_study import result_path
from run_programmatic_release import digest, read, verify_freeze, write_new
from programmatic_release_tasks import render
from programmatic_release_oracle import evaluate
import anchor_checker

ENGLISH_COMPLETED = re.compile(
    r"\b(?:we|our (?:team|study))\s+(?:have\s+)?"
    r"(?:measured|observed|demonstrated|proved|obtained|completed|conducted)\b"
    r"|\b(?:our|this study['\u2019]s)\s+(?:experimental results|measurements)\b",
    re.I,
)


def legacy_decision(legacy, text, review, override, english=False):
    blocked = bool(anchor_checker.check_hypothesis(text))
    english_match = bool(ENGLISH_COMPLETED.search(text))
    state = {
        "quality_target": 90, "hypothesis_score": review["hypothesis_score"],
        "data_score": review["data_score"], "dimensions": copy.deepcopy(review["dimensions"]),
        "anchor_blocked": blocked or (english and english_match),
    }
    result = dict(zip(("plan_status", "evidence_status", "release_reason"),
                      legacy.assess_plan_release(state, passed=True if override else None)))
    return result


def run(study, output):
    if output.exists():
        raise FileExistsError("preserve the previous analysis")
    manifest = verify_freeze(study)
    legacy = legacy_functions(study, manifest)
    environments = read(study / "private_environments.json")
    rows = []
    for unit in read(study / "run_order.json"):
        unit = dict(unit, variant=unit["case_id"].rsplit("_", 1)[-1])
        payload = read(study / "inputs" / (unit["unit_id"] + ".json"))
        result_file = result_path(study, read(study / "scored" / (unit["unit_id"] + ".json")))
        result = read(result_file)
        env = environments[unit["case_id"]]
        if unit["kind"] == "component":
            review = result["review_input"]
        elif unit["arm"] == "A" and unit["variant"] == "T0":
            review = result["history"][-1]["effective_review"]
        else:
            continue
        text, artifact = result["rendered_text"], result["artifact"]
        original = legacy_decision(legacy, text, review, payload["override"])
        assert original == result["decisions"]["A"]
        record = {
            **unit, "source_result": str(result_file), "result_sha256": digest(result_file),
            "artifact": artifact, "text": text, "review": review,
            "truth": evaluate(artifact, env), "A": original,
        }
        if unit["kind"] == "component":
            record["A_English"] = legacy_decision(legacy, text, review, payload["override"], True)
        if unit["kind"] == "workflow" or unit["variant"] == "T1":
            revised = copy.deepcopy(artifact)
            revised["locator"] = "none"
            revised_text = render(revised, payload["public"]["operation"])
            record["locator_removed"] = {
                "artifact": revised, "text": revised_text, "truth": evaluate(revised, env),
                "A": legacy_decision(legacy, revised_text, review, payload["override"]),
            }
            assert record["truth"]["eligible"] and record["locator_removed"]["truth"]["eligible"]
        rows.append(record)
    component = [r for r in rows if r["kind"] == "component"]
    summary = {"component": {}, "locator_counterfactual": {}}
    for arm in ("A", "A_English"):
        summary["component"][arm] = {
            "false_release": sum(r[arm]["plan_status"] == "validated" and not r["truth"]["eligible"]
                                 for r in component),
            "ineligible": sum(not r["truth"]["eligible"] for r in component),
            "eligible_release": sum(r[arm]["plan_status"] == "validated" and r["truth"]["eligible"]
                                    for r in component),
            "eligible": sum(r["truth"]["eligible"] for r in component),
            "by_condition": {
                "T" + str(i): {
                    "released": sum(r[arm]["plan_status"] == "validated" for r in component
                                    if r["variant"] == "T" + str(i)),
                    "n": sum(r["variant"] == "T" + str(i) for r in component),
                } for i in range(8)
            },
        }
    for kind in ("component", "workflow"):
        subset = [r for r in rows if r["kind"] == kind and "locator_removed" in r]
        summary["locator_counterfactual"][kind] = {
            "n": len(subset),
            "original_released": sum(r["A"]["plan_status"] == "validated" for r in subset),
            "edited_released": sum(r["locator_removed"]["A"]["plan_status"] == "validated" for r in subset),
            "edited_eligible": sum(r["locator_removed"]["truth"]["eligible"] for r in subset),
        }
    verify_freeze(study)
    output.mkdir(parents=True)
    write_new(output / "fairness.json", {
        "status": "completed", "api_calls": 0, "design": "post_hoc_fixed_score_sensitivity",
        "source_manifest_sha256": digest(study / "manifest.json"), "summary": summary, "rows": rows,
    })
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    run(args.study.resolve(), args.output.resolve())
