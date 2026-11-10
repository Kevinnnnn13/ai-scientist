"""Recompute saved observations without network access or third-party packages."""

import argparse
from collections import Counter
import copy
import csv
import hashlib
import importlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(root, relative):
    path = (root / relative).resolve()
    require(root.resolve() in path.parents, "path outside bundle: " + relative)
    return path


def no_network(event, args):
    if event.startswith("socket."):
        raise RuntimeError("network disabled during offline reproduction")


def verify_manifest():
    manifest = read(ROOT / "MANIFEST.json")
    actual = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()}
    require(actual == set(manifest["files"]) | {"MANIFEST.json"},
            "bundle file inventory differs from manifest")
    for relative, metadata in manifest["files"].items():
        require(digest(contained(ROOT, relative)) == metadata["sha256"],
                "checksum mismatch: " + relative)
    return len(manifest["files"])


def modules(version):
    names = ("selective_release", "programmatic_release_tasks",
             "programmatic_release_oracle", "anchor_checker",
             "legacy_release", "score_saved")
    sys.path[:] = [p for p in sys.path if p not in
                   (str(ROOT / "code" / "v2"), str(ROOT / "code" / "v21"))]
    sys.path.insert(0, str(ROOT / "code" / version))
    for name in names:
        sys.modules.pop(name, None)
    return SimpleNamespace(**{name: importlib.import_module(name) for name in names})


def verify_study(version, code):
    study = ROOT / "data" / version
    manifest = read(study / "manifest.json")
    require(digest(study / "run_order.json") == manifest["order_sha256"],
            "frozen order mismatch")
    require(digest(study / "private_environments.json") == manifest["environment_sha256"],
            "frozen environment mismatch")
    for relative, expected in manifest["inputs"].items():
        require(digest(contained(study, relative)) == expected, "frozen input mismatch")
    # Exact source files are checked against the original pre-call freeze.
    for name in ("selective_release", "programmatic_release_tasks", "anchor_checker",
                 "programmatic_release_oracle"):
        prefix = "tools/" if name.endswith("_oracle") else "src/"
        source = prefix + name + ".py"
        require(digest(ROOT / "code" / version / (name + ".py")) == manifest["code"][source],
                "frozen source mismatch: " + source)
    require(code.selective_release.ReleasePolicy(**manifest["policy"]).digest ==
            code.selective_release.ReleasePolicy().digest, "unexpected policy")
    order = read(study / "run_order.json")
    require(len(order) == manifest["planned_units"], "planned unit count mismatch")
    require(len({r["unit_id"] for r in order}) == len(order), "duplicate unit IDs")
    for row in order:
        payload = read(study / "inputs" / (row["unit_id"] + ".json"))
        require(set(payload) == {"kind", "public", "initial_artifact", "override",
                                 "arm", "max_rounds"}, "private field in worker input")
        require(set(payload["public"]) == {"operation", "question", "corpus",
                                          "retrieved_context"}, "private public field")
        require(payload["kind"] == row["kind"] and payload["arm"] == row.get("arm"),
                "run order/input mismatch")
    return study, order, read(study / "private_environments.json")


def historical():
    with (ROOT / "data/historical_pilot/per_run_metrics.csv").open(
            encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    require(len({r["run_id"] for r in rows}) == len(rows), "duplicate pilot runs")
    counts = dict(Counter(r["plan_status"] for r in rows))
    require(len(rows) == 72 and counts ==
            {"in_progress": 53, "ungated": 6, "validated": 13}, "pilot counts differ")
    override = [r for r in rows if r["judge_override_condition"] == "1"]
    stress = [r for r in rows if r["is_stress"] == "1"
              and r["judge_override_condition"] == "0"]
    require(len(override) == 12 and all(r["plan_status"] == "validated" for r in override),
            "pilot override counts differ")
    require(len(stress) == 48 and sum(r["plan_status"] != "validated" for r in stress) == 47,
            "pilot stress counts differ")
    return {"runs": len(rows), "plan_status": counts,
            "override_validated": len(override), "other_stress_withheld": 47,
            "other_stress_total": len(stress),
            "scope": "Recount saved summary CSV; not raw-run or scientific-truth revalidation."}


def replay_decision(code, payload, artifact, text, review, arm, saved, counts, policy):
    sr = code.selective_release
    require(text == code.programmatic_release_tasks.render(
        artifact, payload["public"]["operation"]), "rendered text mismatch")
    obj = sr.Candidate(text, review["hypothesis_score"], review["data_score"],
                       copy.deepcopy(review["dimensions"]),
                       payload["public"]["retrieved_context"])
    if arm in ("A", "B"):
        state = {"quality_target": 90, "hypothesis_score": obj.hypothesis_score,
                 "data_score": obj.evidence_score, "dimensions": obj.dimensions,
                 "anchor_blocked": bool(code.anchor_checker.check_hypothesis(text))}
        values = code.legacy_release.assess_plan_release(
            state, passed=True if payload["override"] else None)
        expected = dict(zip(("plan_status", "evidence_status", "release_reason"), values))
        if arm == "B" and expected["plan_status"] == "validated":
            expected.update(plan_status="in_progress", evidence_status="withheld",
                            release_reason="Always withhold validated output.")
        require(expected == saved, arm + " deterministic decision mismatch")
        counts["A_B_decisions_replayed"] += 1
        return
    corpus = sr.Corpus(payload["public"]["corpus"])
    for field, expected in {
        "candidate_sha256": obj.digest, "plan_sha256": sr.sha256_text(text),
        "corpus_sha256": corpus.digest, "policy_sha256": policy.digest,
        "verifier_prompt_sha256": sr.sha256_text(sr.VERIFIER_SYSTEM),
    }.items():
        require(saved[field] == expected, "C binding mismatch: " + field)
    if saved["evidence_check"] == "unavailable":
        require(saved["plan_status"] != "validated", "unavailable verifier released")
        counts["C_unavailable_not_replayed"] += 1
        return
    receipt = saved.get("verification_receipt")

    def recorded_receipt(*args, **kwargs):
        require(receipt is not None, "no saved semantic receipt")
        counts["C_receipts_mechanically_replayed"] += 1
        return copy.deepcopy(receipt)

    expected = sr.SelectiveController(corpus, recorded_receipt, policy).assess(obj)
    # A fresh replay has no historical cache; all substantive fields must match.
    require({k: v for k, v in expected.items() if k != "cache_hit"} ==
            {k: v for k, v in saved.items() if k != "cache_hit"}, "C receipt replay mismatch")
    counts["C_decisions_replayed"] += 1


def development():
    code = modules("v2")
    study, order, environments = verify_study("v2", code)
    policy = code.selective_release.ReleasePolicy(**read(study / "manifest.json")["policy"])
    counts, groups, rows, missing = Counter(), {}, [], []
    for item in order:
        unit = item["unit_id"]
        scorefile = study / "scored" / (unit + ".json")
        if not scorefile.exists():
            missing.append(unit)
            continue
        scored = read(scorefile)
        resultfile = contained(study, scored.get("result_path", "runs/" + unit + "/result.json"))
        require(digest(resultfile) == scored["result_sha256"], "saved result hash mismatch")
        result = read(resultfile)
        require(all(scored[k] == v for k, v in item.items()), "score/order mismatch")
        require(scored["status"] == result["status"], "status mismatch")
        payload = read(study / "inputs" / (unit + ".json"))
        require(result["public_input_sha256"] == code.selective_release.canonical_hash(payload),
                "result/input binding mismatch")
        env = environments[item["case_id"]]
        recomputed = code.score_saved.score_result(result, env)
        require(all(scored[k] == recomputed[k] for k in ("truth", "arms")),
                "independently recomputed scores differ")
        counts["terminal_units"] += 1
        failed = result["status"] != "completed" or any(
            not a["evaluation_valid"] for a in recomputed["arms"].values())
        counts["units_with_execution_failure"] += failed
        counts["units_without_execution_failure"] += not failed
        history = result.get("history", [])
        if history:
            require(result["artifact"] == history[-1]["artifact"]
                    and result["decisions"][item["arm"]] == history[-1]["decision"],
                    "final result/history mismatch")
        entries = history or ([{
            "artifact": result["artifact"], "rendered_text": result["rendered_text"],
            "effective_review": result["review_input"],
        }] if item["kind"] == "component" else [])
        for entry in entries:
            arms = {item["arm"]: entry["decision"]} if history else result["decisions"]
            for arm, decision in arms.items():
                replay_decision(code, payload, entry["artifact"], entry["rendered_text"],
                                entry["effective_review"], arm, decision, counts, policy)
        for arm in ("ABC" if item["kind"] == "component" else (item["arm"],)):
            score = recomputed["arms"].get(arm, {})
            row = {"unit_id": unit, "case_id": item["case_id"], "kind": item["kind"],
                   "controller": arm, "status": result["status"],
                   "evaluation_valid": score.get("evaluation_valid", False),
                   "eligible": score.get("eligible"), "released": score.get("released", False)}
            for key in ("false_release", "false_rejection", "safe_withhold",
                        "released_task_success", "released_safe_narrowing"):
                row[key] = score.get(key, False)
            rows.append(row)
            groupkey = ":".join((item["kind"], item["case_id"].rsplit("_", 1)[1], arm))
            group = groups.setdefault(groupkey, Counter())
            group["attempted"] += 1
            group["valid"] += row["evaluation_valid"]
            group["execution_failure"] += not row["evaluation_valid"]
            if row["evaluation_valid"]:
                for key in ("released", "false_release", "false_rejection", "safe_withhold",
                            "released_task_success", "released_safe_narrowing"):
                    group[key] += row[key]
                group["eligible"] += row["eligible"]
                group["ineligible"] += not row["eligible"]
    api, models, tokens = Counter(), Counter(), Counter()
    for parent in ("runs", "attempts"):
        for trace in sorted((study / parent).rglob("api_trace.jsonl")):
            for line in trace.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                api[event["status"]] += 1
                response = event.get("response", {})
                if response.get("model"):
                    models[response["model"]] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    tokens[key] += (response.get("usage") or {}).get(key, 0) or 0
    require(counts["terminal_units"] == 11 and counts["units_without_execution_failure"] == 8
            and counts["units_with_execution_failure"] == 3, "development counts differ")
    require(dict(api) == {"received": 15, "api_error": 6}, "API event counts differ")
    require(tokens["total_tokens"] == 16327, "recorded usage differs")
    return {"planned_units": len(order), **dict(counts), "not_started_units": missing,
            "api_events": dict(api), "returned_model_ids": dict(models),
            "recorded_tokens": dict(tokens), "groups": groups, "outcomes": rows,
            "scope": "v2 development only; semantic receipts are reused, not independently judged.",
            "unknown_usage": "Interrupted requests without responses may have unrecorded billed usage."}


def prepared():
    code = modules("v21")
    study, order, environments = verify_study("v21", code)
    readiness = read(study / "READINESS.json")
    require(readiness["model_calls_started"] is False, "prepared study has calls")
    eligible = Counter()
    for row in order:
        payload = read(study / "inputs" / (row["unit_id"] + ".json"))
        if row["kind"] != "component":
            continue
        truth = code.programmatic_release_oracle.evaluate(
            payload["initial_artifact"], environments[row["case_id"]])
        condition = row["case_id"].rsplit("_", 1)[1]
        require(truth["judgeable"] and truth["eligible"] == (condition in ("T0", "T1")),
                "prepared positive/negative material mismatch")
        eligible["eligible" if truth["eligible"] else "ineligible"] += 1
    require(dict(eligible) == {"ineligible": 18, "eligible": 6}, "prepared counts differ")
    return {"planned_units": len(order), "component_inputs": sum(eligible.values()),
            "component_material_eligibility": dict(eligible),
            "planned_generation_loops": sum(r["kind"] == "workflow" for r in order),
            "model_observations": 0, "formal_evaluation_completed": False}


def reproduce():
    sys.addaudithook(no_network)
    checked = verify_manifest()
    return {"status": "passed", "files_verified": checked, "network": "disabled",
            "historical_pilot": historical(), "v2_development": development(),
            "v21_prepared": prepared()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", help="Optional NEW JSON file outside this bundle.")
    args = parser.parse_args()
    result = reproduce()
    if args.output:
        output = Path(args.output).resolve()
        require(ROOT not in output.parents and output != ROOT, "output must be outside bundle")
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
    compact = copy.deepcopy(result)
    compact["v2_development"].pop("outcomes")
    compact["v2_development"].pop("groups")
    print(json.dumps(compact, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError, TypeError) as exc:
        print("OFFLINE AUDIT FAILED: " + str(exc), file=sys.stderr)
        sys.exit(1)
