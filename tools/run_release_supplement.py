"""Freeze and run paired public-input C/D evaluations with separate scoring."""

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import zipfile

from run_programmatic_release import ROOT, code_manifest, digest, read, verify_freeze, write_new
from continue_controlled_study import result_path
from programmatic_release_oracle import evaluate
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController, canonical_hash
from release_supplement_worker import D_SYSTEM, D_SCHEMA

EXTRA = (
    "tools/release_supplement_worker.py", "tools/run_release_supplement.py",
    "tools/release_fairness_check.py", "tests/test_release_supplement.py",
    "docs/release_supplement_protocol_20261015.md",
)


def prepare(source, study):
    if study.exists():
        raise FileExistsError("supplement must use a new directory")
    manifest = verify_freeze(source)
    rows = [r for r in read(source / "run_order.json") if r["kind"] == "component"]
    random.Random(20261015).shuffle(rows)
    study.mkdir(parents=True)
    pairs, input_hashes, bindings = [], {}, {}
    for index, row in enumerate(rows):
        old = read(source / "inputs" / (row["unit_id"] + ".json"))
        saved = read(source / "scored" / (row["unit_id"] + ".json"))
        old_result = result_path(source, saved)
        bindings[row["unit_id"]] = {
            "result_path": str(old_result), "sha256": digest(old_result),
        }
        pair = {
            "pair_id": f"p{index + 1:03d}", "case_id": row["case_id"],
            "original_unit": row["unit_id"], "arms": ["C", "D"] if index % 2 == 0 else ["D", "C"],
        }
        pairs.append(pair)
        for arm in pair["arms"]:
            payload = {k: old[k] for k in ("public", "initial_artifact", "override")}
            payload["arm"] = arm
            target = study / "inputs" / (pair["pair_id"] + "_" + arm + ".json")
            write_new(target, payload)
            input_hashes[target.relative_to(study).as_posix()] = digest(target)
    write_new(study / "pairs.json", pairs)
    write_new(study / "private_environments.json", read(source / "private_environments.json"))
    code = code_manifest()
    code.update({name: digest(ROOT / name) for name in EXTRA})
    with zipfile.ZipFile(study / "source_snapshot.zip", "x", zipfile.ZIP_DEFLATED) as zipped:
        for name in code:
            zipped.write(ROOT / name, name)
    write_new(study / "manifest.json", {
        "status": "frozen_before_calls", "study_version": "posthoc-cd-v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "source_study": str(source),
        "source_manifest_sha256": digest(source / "manifest.json"),
        "code": code, "inputs": input_hashes, "original_results": bindings,
        "pairs_sha256": digest(study / "pairs.json"),
        "environment_sha256": digest(study / "private_environments.json"),
        "source_snapshot_sha256": digest(study / "source_snapshot.zip"),
        "model": manifest["model"], "D_system": D_SYSTEM, "D_schema": D_SCHEMA,
        "planned_pairs": 48, "planned_evaluations": 96,
        "sampling": "Reused inspected component inputs; post hoc, not new holdout.",
        "request_settings": {"temperature": 0, "max_tokens": 8192, "timeout": 120,
                             "sdk_max_retries": 0, "json_max_retries": 1},
    })
    print(json.dumps({"frozen": str(study), "pairs": 48, "evaluations": 96}))


def verify(study):
    manifest = read(study / "manifest.json")
    verify_freeze(Path(manifest["source_study"]))
    for path, expected in manifest["code"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("changed code: " + path)
    for path, expected in manifest["inputs"].items():
        if digest(study / path) != expected:
            raise ValueError("changed public input")
    for name, key in (("pairs.json", "pairs_sha256"),
                      ("private_environments.json", "environment_sha256"),
                      ("source_snapshot.zip", "source_snapshot_sha256")):
        if digest(study / name) != manifest[key]:
            raise ValueError("changed frozen study file: " + name)
    for binding in manifest["original_results"].values():
        if digest(binding["result_path"]) != binding["sha256"]:
            raise ValueError("changed original result")
    return manifest


def score(study, pair, arm):
    name = pair["pair_id"] + "_" + arm
    path = study / "runs" / name / "result.json"
    result = read(path)
    payload = read(study / "inputs" / (name + ".json"))
    assert result["public_input_sha256"] == canonical_hash(payload)
    env = read(study / "private_environments.json")[pair["case_id"]]
    truth = evaluate(result["artifact"], env)
    decision = result["decisions"].get(arm)
    valid = result["status"] == "completed" and truth["judgeable"] and decision is not None
    released = valid and decision["plan_status"] == "validated"
    record = {
        "name": name, **pair, "arm": arm, "condition": pair["case_id"].rsplit("_", 1)[-1],
        "status": result["status"], "valid": valid, "released": released,
        "truth": truth, "result_sha256": digest(path),
        "false_release": valid and released and not truth["eligible"],
        "false_rejection": valid and not released and truth["eligible"],
        "usage": result.get("usage", {}),
    }
    destination = study / "scored" / (name + ".json")
    if destination.exists():
        assert read(destination) == record
    else:
        write_new(destination, record)
    return record


def execute_pair(study, pair):
    records = []
    for arm in pair["arms"]:
        name = pair["pair_id"] + "_" + arm
        output = study / "runs" / name
        if output.exists() and not (output / "result.json").exists():
            raise RuntimeError("interrupted unit preserved: " + name)
        if not (output / "result.json").exists():
            logs = study / "launcher_logs"
            logs.mkdir(exist_ok=True)
            env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1",
                       LLM_BACKEND="deepseek")
            with (logs / (name + ".txt")).open("x", encoding="utf-8") as log:
                subprocess.run([
                    sys.executable, "-B", "-X", "utf8",
                    str(ROOT / "tools/release_supplement_worker.py"),
                    "--input", str(study / "inputs" / (name + ".json")), "--output", str(output),
                ], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=360, check=False)
        record = score(study, pair, arm)
        records.append(record)
        print(json.dumps({k: record[k] for k in ("name", "condition", "valid", "released")}), flush=True)
        if not record["valid"]:
            break
    return records


def semantic_only(receipt):
    rows = receipt["units"]
    return (
        any(r["kind"] == "factual" for r in rows)
        and all((r["kind"] == "factual" and r["verdict"] == "supported")
                or (r["kind"] in ("planned", "heading") and r["verdict"] == "not_applicable")
                for r in rows)
    )


def analyze(study):
    verify(study)
    rows = [read(path) for path in sorted((study / "scored").glob("*.json"))]
    groups = {}
    for arm in ("C", "D"):
        subset = [r for r in rows if r["arm"] == arm and r["valid"]]
        groups[arm] = {
            "planned": 48, "valid": len(subset),
            "ineligible": sum(not r["truth"]["eligible"] for r in subset),
            "eligible": sum(r["truth"]["eligible"] for r in subset),
            "false_release": sum(r["false_release"] for r in subset),
            "eligible_release": sum(r["released"] and r["truth"]["eligible"] for r in subset),
            "false_rejection": sum(r["false_rejection"] for r in subset),
            "by_condition": {"T" + str(i): {
                "valid": sum(r["condition"] == "T" + str(i) for r in subset),
                "released": sum(r["released"] and r["condition"] == "T" + str(i) for r in subset),
            } for i in range(8)},
        }
    replay_rows, api_events, models, tokens = [], Counter(), Counter(), Counter()
    for row in rows:
        result_dir = study / "runs" / row["name"]
        trace_path = result_dir / "api_trace.jsonl"
        trace = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()] if trace_path.exists() else []
        for event in trace:
            api_events[event["status"]] += 1
            if event["status"] == "received":
                response = event["response"]
                models[response["model"]] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    tokens[key] += response.get("usage", {}).get(key, 0)
        if not row["valid"]:
            continue
        result = read(result_dir / "result.json")
        payload = read(study / "inputs" / (row["name"] + ".json"))
        review = result["review_input"]
        obj = Candidate(result["rendered_text"], review["hypothesis_score"], review["data_score"],
                        review["dimensions"], payload["public"]["retrieved_context"])
        saved = result["decisions"][row["arm"]]
        raw_receipts = []
        from llm_client import extract_json
        for event in trace:
            if event["status"] == "received":
                raw_receipts.append(extract_json(event["response"]["choices"][0]["message"]["content"]))
        if row["arm"] == "C":
            receipt = saved["verification_receipt"]
            assert receipt in raw_receipts
            expected = SelectiveController(
                Corpus(payload["public"]["corpus"]), lambda *a, **k: receipt, ReleasePolicy()
            ).assess(obj)
            assert expected == saved
            replay_rows.append({
                "name": row["name"], "full_release": row["released"],
                "semantic_only_release": semantic_only(receipt), "eligible": row["truth"]["eligible"],
            })
        else:
            assert saved["review_receipt"] in raw_receipts
            from release_supplement_worker import assess_d
            expected = assess_d(obj, Corpus(payload["public"]["corpus"]),
                                lambda *a, **k: saved["review_receipt"], ReleasePolicy())
            assert expected == saved
    lookup = {(r["pair_id"], r["arm"]): r for r in rows}
    paired = Counter()
    for pair in read(study / "pairs.json"):
        c, d = lookup.get((pair["pair_id"], "C")), lookup.get((pair["pair_id"], "D"))
        if c and d and c["valid"] and d["valid"]:
            paired[f"C_{int(c['released'])}_D_{int(d['released'])}"] += 1
    summary = {
        "planned": 96, "completed": len(rows), "execution_failures": sum(not r["valid"] for r in rows),
        "groups": groups, "paired_release_decisions": dict(paired), "api_events": dict(api_events),
        "response_models": dict(models), "tokens": dict(tokens),
        "C_receipt_diagnostic": {
            "n": len(replay_rows),
            "changed_decisions": sum(r["full_release"] != r["semantic_only_release"] for r in replay_rows),
            "rows": replay_rows,
        },
        "mechanical_replay_and_raw_binding": "passed",
        "design": "post_hoc_reused_inputs_not_new_holdout",
    }
    target = study / "summary.json"
    if target.exists():
        assert read(target) == summary
    else:
        write_new(target, summary)
    print(json.dumps({k: v for k, v in summary.items() if k != "C_receipt_diagnostic"}, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "analyze"))
    parser.add_argument("--study", required=True, type=Path)
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    study = args.study.resolve()
    if args.command == "prepare":
        prepare(args.source.resolve(), study)
    elif args.command == "run":
        verify(study)
        pairs = read(study / "pairs.json")
        with ThreadPoolExecutor(max_workers=3) as pool:
            for start in range(0, len(pairs), 3):
                futures = [pool.submit(execute_pair, study, pair) for pair in pairs[start:start + 3]]
                records = [row for future in futures for row in future.result()]
                if any(not row["valid"] for row in records):
                    print("Stopped after draining a batch with execution/protocol failure.", flush=True)
                    return 2
        analyze(study)
    else:
        analyze(study)
    return 0


if __name__ == "__main__":
    sys.exit(main())
