"""Export blinded review materials and a descriptive DEVELOPMENT-only rollup."""

import argparse
import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from selective_release import canonical_hash, sha256_text
from prepare_release_study import write_json


def export(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    artifacts, component_rows, workflow_rows = [], [], []
    total_usage = Counter()
    for path in sorted((root / "component").glob("T?.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        spec_path = root / "materials" / path.name
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        corpus = json.loads((spec_path.parent / spec["corpus_path"]).read_text(encoding="utf-8"))
        text = (spec_path.parent / spec["plan_path"]).read_text(encoding="utf-8")
        content = {"question": spec["question"], "plan": text, "available_sources": corpus}
        artifacts.append((content, {"kind": "component", "variant": spec["variant"],
                                    "source_file": str(spec_path), "plan_selection": "fixed_component_input"}))
        row = {"variant": spec["variant"], **{arm: result["decisions"][arm]["plan_status"] for arm in "ABC"},
               "C_errors": result["decisions"]["C"]["errors"], "usage": result["usage_delta"]}
        component_rows.append(row)
        total_usage.update(result["usage_delta"])
    paths = sorted((root / "workflow").glob("*/result.json"))
    paths += sorted((root / "feedback_recheck").glob("*/result.json"))
    for path in paths:
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("phase") != "development":
            raise ValueError("This exporter accepts development results only")
        state = json.loads(Path(result["state_path"]).read_text(encoding="utf-8"))
        spec_path = root / "materials" / (result["variant"] + ".json")
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if result["controller"] == "A":
            text = state.get("best_hypothesis") or state.get("hypothesis") or ""
            selection = "best_hypothesis_or_current_as_used_by_A_delivery"
        else:
            text = state.get("approved_hypothesis") if result["plan_status"] == "validated" else state.get("hypothesis")
            selection = "approved_or_current_as_used_by_C_delivery"
        if not text:
            raise ValueError("Missing final plan")
        corpus = json.loads((spec_path.parent / spec["corpus_path"]).read_text(encoding="utf-8"))
        content = {"question": spec["question"], "plan": text, "available_sources": corpus}
        group = "feedback_recheck" if "feedback_recheck" in path.parts else "initial_workflow"
        artifacts.append((content, {"kind": "workflow", "variant": result["variant"],
                                    "controller": result["controller"], "source_file": str(path),
                                    "plan_selection": selection, "revision_group": group,
                                    "reported_plan_status": result["plan_status"]}))
        events = [json.loads(line) for line in (path.parent / "release_events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        row = {"run": str(path.parent.relative_to(root)), "variant": result["variant"],
               "controller": result["controller"], "group": group, "plan_status": result["plan_status"],
               "exit_code": result["exit_code"], "seconds": result["seconds"], "usage": result["api_usage"],
               "runtime_counts": result["runtime_counts"], "rounds": state.get("rounds"),
               "effective_score": state.get("hypothesis_score"), "effective_evidence_score": state.get("data_score"),
               "release_reason": result["release_reason"], "final_plan_sha256": sha256_text(text),
               "generator_feedback_events": sum(event["event"] == "release_feedback_to_generator" for event in events),
               "human_eligibility": "pending"}
        workflow_rows.append(row)
        total_usage.update(result["api_usage"])
    rechecks = []
    for path in sorted((root / "quote_layout_recheck").glob("live_*.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        total_usage.update(result["usage_delta"])
        rechecks.append({"variant": result["variant"], "C": result["decisions"]["C"]["plan_status"],
                         "C_errors": result["decisions"]["C"]["errors"], "usage": result["usage_delta"]})
    review_entries = len(artifacts)
    unique = {}
    for content, private in artifacts:
        digest = canonical_hash(content)
        if digest not in unique:
            unique[digest] = (content, [])
        unique[digest][1].append(private)
    artifacts = list(unique.values())
    random.Random(2026101401).shuffle(artifacts)
    mapping, forms = [], []
    packet = output / "reviewers"
    packet.mkdir()
    for i, (content, private) in enumerate(artifacts, 1):
        blind_id = "D%03d" % i
        digest = canonical_hash(content)
        write_json(packet / (blind_id + ".json"), {"blind_id": blind_id, "artifact_sha256": digest, **content})
        lines = ["# " + blind_id, "", "## Question", "", content["question"], "", "## Plan", "", content["plan"], "", "## Available source passages", ""]
        for source in content["available_sources"]["sources"]:
            lines += ["### " + source["id"], "", source["title"], "", "Origin: " + source["origin"], ""]
            for passage in source["passages"]:
                lines += ["Passage: " + passage["id"] + "; locator: " + passage["locator"], "", passage["text"], ""]
        with (packet / (blind_id + ".md")).open("x", encoding="utf-8") as stream:
            stream.write("\n".join(lines))
        mapping.append({"blind_id": blind_id, "artifact_sha256": digest, "origins": private})
        forms.append({"blind_id": blind_id, "artifact_sha256": digest, "reviewer_id": "",
                      "premises_supported": None, "conflicts_handled": None,
                      "no_fabricated_completed_work": None, "quality_requirements_met": None,
                      "eligibility": None, "source_references": [], "reason": ""})
    write_json(output / "PRIVATE_mapping_do_not_send_to_reviewers.json", mapping)
    for role in ("R1", "R2"):
        write_json(packet / (role + "_blank_annotations.json"), copy.deepcopy(forms))
    summary = {"phase": "development", "not_formal_study_data": True, "formal_runs_completed": 0,
               "initial_component_decisions": len(component_rows) * 3, "component_results": component_rows,
               "workflow_results": workflow_rows, "live_quote_rechecks": rechecks,
               "replayed_old_receipts": 8, "replay_api_calls": 0,
               "total_recorded_usage": dict(total_usage),
               "total_tokens": total_usage["prompt_tokens"] + total_usage["completion_tokens"],
               "review_entries_covered": review_entries,
               "unique_review_artifacts": len(artifacts), "human_annotations_completed": 0,
               "cost_cny": None, "cost_note": "Do not use the legacy hard-coded token price as actual billing.",
               "warning": "Do not combine code revisions or treat development fixture expectations as human gold labels."}
    write_json(output / "development_summary.json", summary)
    table = ["# Development pilot results", "", "NOT FORMAL STUDY DATA. All human eligibility labels are pending.", "", "## Initial component decisions", "", "| Condition | A | B | C |", "| --- | --- | --- | --- |"]
    table += ["| {variant} | {A} | {B} | {C} |".format(**row) for row in component_rows]
    table += ["", "## Workflow decisions", "", "| Run | Status | Exit | API calls | Generator feedback events |", "| --- | --- | --- | --- | --- |"]
    table += ["| %s | %s | %s | %s | %s |" % (row["run"], row["plan_status"], row["exit_code"], row["usage"]["calls"], row["generator_feedback_events"]) for row in workflow_rows]
    table += ["", "## Quote-layout rechecks", "", "Original failures are preserved. These are new development API calls, not formal replicates.", ""]
    table += ["- %s: C=%s; errors=%s" % (row["variant"], row["C"], row["C_errors"]) for row in rechecks]
    table += ["", "Recorded API calls: %s; recorded total tokens: %s." % (total_usage["calls"], summary["total_tokens"]),
              "", "Human review artifacts: %s; two independent reviews are required per artifact." % len(artifacts),
              "", "Only the reviewers subfolder is intended for blinded annotation. The private mapping and results must be withheld from reviewers until labels are locked."]
    with (output / "RESULTS.md").open("x", encoding="utf-8") as stream:
        stream.write("\n".join(table) + "\n")
    print(json.dumps({"output": str(output), "artifacts": len(artifacts), "formal_runs": 0,
                      "usage": dict(total_usage), "total_tokens": summary["total_tokens"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    export(args.input, args.output)
