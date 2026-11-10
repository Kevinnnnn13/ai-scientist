"""Audit every saved decision and artifact, including intermediate rounds."""

import argparse
import ast
from collections import Counter
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

from run_programmatic_release import digest, read, verify_freeze, write_new
from continue_controlled_study import check_saved_score, result_path
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController
from programmatic_release_tasks import render, review_input
from programmatic_release_oracle import evaluate
import anchor_checker


def require(condition, message):
    if not condition:
        raise ValueError(message)


def legacy_functions(study, manifest):
    with zipfile.ZipFile(study / "frozen_source.zip") as zipped:
        raw = zipped.read("src/langgraph_agent.py")
    import hashlib
    require(hashlib.sha256(raw).hexdigest() == manifest["code"]["src/langgraph_agent.py"],
            "legacy source snapshot mismatch")
    tree = ast.parse(raw.decode("utf-8-sig"))
    names = {"floor_for", "novelty_floor_for", "pass_check",
             "exploratory_check", "assess_plan_release"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef)
             and node.name in names]
    nodes += [node for node in tree.body if isinstance(node, ast.Assign)
              and any(isinstance(t, ast.Name) and t.id == "MAX_DATA_ROUNDS" for t in node.targets)]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "frozen_legacy_release", "exec"),
         namespace)
    return SimpleNamespace(**namespace)


def decisions_match(legacy, payload, text, review, saved, arm, policy, counts):
    obj = Candidate(text, review["hypothesis_score"], review["data_score"],
                    copy.deepcopy(review["dimensions"]), payload["public"]["retrieved_context"])
    if arm in ("A", "B"):
        state = {"quality_target": 90, "hypothesis_score": obj.hypothesis_score,
                 "data_score": obj.evidence_score, "dimensions": obj.dimensions,
                 "anchor_blocked": bool(anchor_checker.check_hypothesis(text))}
        expected = dict(zip(("plan_status", "evidence_status", "release_reason"),
                            legacy.assess_plan_release(
                                state, passed=True if payload["override"] else None)))
        if arm == "B" and expected["plan_status"] == "validated":
            expected.update(plan_status="in_progress", evidence_status="withheld",
                            release_reason="Always withhold validated output.")
        require(expected == saved, "deterministic legacy decision mismatch")
        counts["legacy_decisions_replayed"] += 1
        return
    if saved["evidence_check"] == "unavailable":
        require(saved["plan_status"] != "validated", "unavailable verifier released")
        counts["unavailable_C_not_replayed"] += 1
        return
    receipt = saved.get("verification_receipt")

    def replay(*args, **kwargs):
        require(receipt is not None, "missing saved receipt")
        counts["receipts_mechanically_replayed"] += 1
        return copy.deepcopy(receipt)

    expected = SelectiveController(Corpus(payload["public"]["corpus"]), replay, policy).assess(obj)
    require({k: v for k, v in expected.items() if k != "cache_hit"} ==
            {k: v for k, v in saved.items() if k != "cache_hit"},
            "C mechanical replay differs")
    counts["C_decisions_replayed"] += 1


def audit(study):
    manifest = verify_freeze(study)
    legacy = legacy_functions(study, manifest)
    policy = ReleasePolicy(**manifest["policy"])
    environments = read(study / "private_environments.json")
    order = read(study / "run_order.json")
    counters, details = Counter(), []
    for row in order:
        unit, environment = row["unit_id"], environments[row["case_id"]]
        scorefile = study / "scored" / (unit + ".json")
        require(scorefile.exists(), "unit lacks terminal score: " + unit)
        scored = check_saved_score(study, row, environment)
        resultfile = result_path(study, scored)
        result = read(resultfile)
        payload = read(study / "inputs" / (unit + ".json"))
        counters["final_artifacts_recomputed"] += 1
        tracefile = resultfile.parent / "api_trace.jsonl"
        response_objects = []
        if tracefile.exists():
            for line in tracefile.read_text(encoding="utf-8").splitlines():
                trace = json.loads(line)
                if trace["status"] != "received":
                    continue
                try:
                    response_objects.append(json.loads(
                        trace["response"]["choices"][0]["message"]["content"]))
                except (ValueError, KeyError, TypeError):
                    counters["raw_responses_not_plain_json"] += 1
        history = result.get("history", [])
        if history:
            require(result["artifact"] == history[-1]["artifact"]
                    and result["decisions"][row["arm"]] == history[-1]["decision"],
                    "terminal/history mismatch: " + unit)
        entries = history or ([{
            "artifact": result["artifact"], "rendered_text": result["rendered_text"],
            "effective_review": result["review_input"],
        }] if row["kind"] == "component" else [])
        truths = []
        for entry in entries:
            truth = evaluate(entry["artifact"], environment)
            truths.append(truth)
            require(render(entry["artifact"], payload["public"]["operation"]) ==
                    entry["rendered_text"], "render mismatch: " + unit)
            if history:
                counters["generation_round_artifacts_recomputed"] += 1
                require(entry["artifact"] in response_objects,
                        "generated artifact absent from raw responses: " + unit)
                require(entry["original_review"] in response_objects,
                        "review absent from raw responses: " + unit)
                require(entry["override_applied"] == payload["override"], "override flag mismatch")
                expected_review = copy.deepcopy(entry["original_review"])
                if payload["override"]:
                    expected_review = review_input(True)
                    expected_review["feedback"] = "Reviewer recommends release."
                require(entry["effective_review"] == expected_review, "effective override mismatch")
                arms = {row["arm"]: entry["decision"]}
            else:
                require(entry["effective_review"] == review_input(payload["override"]),
                        "component controlled score mismatch")
                arms = result["decisions"]
            for arm, saved in arms.items():
                decisions_match(legacy, payload, entry["rendered_text"], entry["effective_review"],
                                saved, arm, policy, counters)
                receipt = saved.get("verification_receipt")
                if receipt is not None and not saved.get("cache_hit"):
                    require(receipt in response_objects, "receipt absent from raw responses: " + unit)
                    counters["receipts_bound_to_raw_response"] += 1
        details.append({
            "unit_id": unit, "kind": row["kind"], "case_id": row["case_id"],
            "result_sha256": digest(resultfile), "final_truth": scored["truth"],
            "round_truth": truths,
            "execution_failure": result["status"] != "completed" or
                                 any(not a["evaluation_valid"] for a in scored["arms"].values()),
        })
    return {"status": "passed", "phase": manifest["phase"], "units": len(order),
            "counts": dict(counters), "details": details,
            "scope": "Independent artifact scoring plus deterministic policy and saved-receipt replay. "
                     "Not a new semantic-model judgment or an independent human audit."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output)
    require(not output.exists(), "use a new audit output file")
    result = audit(Path(args.study).resolve())
    write_new(output, result)
    print(json.dumps({k: result[k] for k in ("status", "phase", "units", "counts")}))


if __name__ == "__main__":
    main()
