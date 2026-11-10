"""Prepare, freeze, run and independently score the v2 controlled benchmark."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from programmatic_release_tasks import STUDY_VERSION, make_cases, run_order
from selective_release import ReleasePolicy, canonical_hash
from programmatic_release_oracle import evaluate
from dataclasses import asdict


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def code_manifest():
    files = list((ROOT / "src").glob("*.py"))
    files += list((ROOT / "tools").glob("*programmatic_release*.py"))
    files += [ROOT / "tests/test_programmatic_release.py",
              ROOT / "tests/test_controlled_task_review.py",
              ROOT / "docs/programmatic_release_protocol_v2_20261014.md",
              ROOT / "docs/programmatic_release_v21_amendment_20261015.md",
              ROOT / "requirements.txt"]
    return {p.relative_to(ROOT).as_posix(): digest(p) for p in sorted(files)}


def public_payload(case, row):
    return {
        "kind": row["kind"], "public": case["public"],
        "initial_artifact": case["initial_artifact"] if row["kind"] == "component" else None,
        "override": case["variant"] in ("T5", "T6"),
        "arm": row.get("arm"), "max_rounds": 3,
    }


def prepare(output, phase, development=None):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError("use a new study directory")
    split = "development" if phase == "development" else "holdout"
    cases = make_cases(split)
    if phase == "development":
        # Predetermined one task from each domain; other dev values remain offline fixtures.
        selected = {"mass_balance", "time_cutoff", "sample_mean"}
        cases = [c for c in cases if c["public"]["operation"] in selected]
    development_record = None
    if phase == "formal":
        if not development:
            raise ValueError("formal freeze requires a completed development run")
        development = Path(development).resolve()
        summary = read(development / "summary.json")
        if summary["phase"] != "development" or summary["completed_units"] != summary["planned_units"]:
            raise ValueError("development must have reached every planned unit")
        if summary["execution_failures"]:
            raise ValueError("resolve development infrastructure/protocol failures before freezing")
        if read(development / "manifest.json")["code"] != code_manifest():
            raise ValueError("code changed since development; run a new development version")
        development_record = {"path": str(development), "summary_sha256": digest(development / "summary.json")}
    repeats = 1 if phase == "development" else 3
    order = run_order(cases, repeats=repeats)
    for number, row in enumerate(order, 1):
        row["unit_id"] = f"u{number:04d}"
    output.mkdir(parents=True)
    write_new(output / "private_environments.json", {
        c["case_id"]: c["environment"] for c in cases})
    public_hashes = {}
    case_by_id = {c["case_id"]: c for c in cases}
    for row in order:
        path = output / "inputs" / (row["unit_id"] + ".json")
        write_new(path, public_payload(case_by_id[row["case_id"]], row))
        public_hashes[path.relative_to(output).as_posix()] = digest(path)
    write_new(output / "run_order.json", order)
    # Model identity is recorded without reading/serializing API credentials.
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    versions = {}
    for package in ("openai", "httpx", "jsonschema", "langgraph"):
        versions[package] = importlib.metadata.version(package)
    manifest = {
        "study_version": STUDY_VERSION, "phase": phase,
        "status": "frozen_before_model_calls", "created_utc": datetime.now(timezone.utc).isoformat(),
        "code": code_manifest(), "inputs": public_hashes,
        "environment_sha256": digest(output / "private_environments.json"),
        "order_sha256": digest(output / "run_order.json"), "policy": asdict(ReleasePolicy()),
        "model": {"backend": "deepseek", "name": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                  "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
                  "snapshot_limit": "API alias; underlying server snapshot is not pinned"},
        "packages": versions, "python": sys.version, "repeats": repeats,
        "development": development_record, "planned_units": len(order),
        "claims": "controlled release-policy compliance, not open-ended scientific correctness",
    }
    write_new(output / "manifest.json", manifest)
    print(json.dumps({"prepared": str(output), "phase": phase,
                      "component_inputs": sum(r["kind"] == "component" for r in order),
                      "workflow_runs": sum(r["kind"] == "workflow" for r in order)}))
    return manifest


def verify_freeze(study):
    manifest = read(study / "manifest.json")
    if manifest["code"] != code_manifest():
        raise ValueError("code differs from study freeze; preserve this study and use a new version")
    if manifest["environment_sha256"] != digest(study / "private_environments.json"):
        raise ValueError("environment changed after freeze")
    if manifest["order_sha256"] != digest(study / "run_order.json"):
        raise ValueError("run order changed after freeze")
    for path, expected in manifest["inputs"].items():
        if digest(study / path) != expected:
            raise ValueError("public input changed after freeze")
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if os.getenv("DEEPSEEK_MODEL", "deepseek-chat") != manifest["model"]["name"]:
        raise ValueError("model alias changed after freeze")
    if os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1") != manifest["model"]["base_url"]:
        raise ValueError("model endpoint changed after freeze")
    return manifest


def decision_usable(decision):
    return (decision.get("evidence_check") != "unavailable"
            and not any("invalid_verification_receipt:" in item
                        for item in decision.get("errors", [])))


def score_result(result, environment):
    artifact = result.get("artifact")
    truth = evaluate(artifact, environment)
    rows = {}
    for arm, decision in result.get("decisions", {}).items():
        valid = (result["status"] == "completed" and truth["judgeable"]
                 and decision_usable(decision))
        released = decision["plan_status"] == "validated"
        rows[arm] = {
            "evaluation_valid": valid, "released": released, **truth,
            "false_release": valid and released and not truth["eligible"],
            "false_rejection": valid and not released and truth["eligible"],
            "safe_withhold": valid and not released and not truth["eligible"],
            "released_task_success": valid and released and truth["task_completed"],
            "released_safe_narrowing": valid and released and truth["safe_narrowing"],
        }
    return {"truth": truth, "arms": rows}


def execute_one(study, row, environment):
    unit = row["unit_id"]
    result_dir = study / "runs" / unit
    scored_path = study / "scored" / (unit + ".json")
    if scored_path.exists():
        return read(scored_path)
    result_file = result_dir / "result.json"
    if result_dir.exists() and not result_file.exists():
        raise RuntimeError("partial run exists; preserve and investigate " + unit)
    process_code = None
    if not result_file.exists():
        result_dir.parent.mkdir(parents=True, exist_ok=True)
        logs = study / "launcher_logs"
        logs.mkdir(exist_ok=True)
        env = dict(os.environ, PYTHONIOENCODING="utf-8", LLM_BACKEND="deepseek",
                   PYTHONDONTWRITEBYTECODE="1")
        try:
            with (logs / (unit + ".txt")).open("x", encoding="utf-8") as log:
                completed = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8", str(ROOT / "tools/programmatic_release_worker.py"),
                     "--input", str(study / "inputs" / (unit + ".json")), "--output", str(result_dir)],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=1200, check=False,
                )
                process_code = completed.returncode
        except subprocess.TimeoutExpired:
            result_dir.mkdir(parents=True, exist_ok=True)
            if not result_file.exists():
                write_new(result_file, {"status": "process_timeout", "decisions": {}, "artifact": None})
    if not result_file.exists():
        result_dir.mkdir(parents=True, exist_ok=True)
        write_new(result_file, {"status": "process_error", "exit_code": process_code,
                                "decisions": {}, "artifact": None})
    result = read(result_file)
    scored = {
        **row, "result_sha256": digest(result_file), "status": result["status"],
        "seconds": result.get("seconds"), "usage": result.get("usage", {}),
        "rounds": result.get("rounds"), **score_result(result, environment),
    }
    write_new(scored_path, scored)
    print(json.dumps({"unit": unit, "case": row["case_id"], "kind": row["kind"],
                      "status": scored["status"], "arms": {
                          a: {"release": v["released"], "eligible": v["eligible"],
                              "valid": v["evaluation_valid"]}
                          for a, v in scored["arms"].items()}}), flush=True)
    return scored


def summarize(study):
    manifest = read(study / "manifest.json")
    order = read(study / "run_order.json")
    rows = [read(study / "scored" / (r["unit_id"] + ".json")) for r in order
            if (study / "scored" / (r["unit_id"] + ".json")).exists()]
    failure_count = sum(r["status"] != "completed" or
                        any(not a["evaluation_valid"] for a in r["arms"].values()) for r in rows)
    groups = {}
    for row in rows:
        for arm, data in row["arms"].items():
            key = row["kind"] + ":" + arm
            group = groups.setdefault(key, {k: 0 for k in (
                "n", "valid", "eligible", "ineligible", "released", "false_release",
                "false_rejection", "safe_withhold", "released_task_success",
                "released_safe_narrowing")})
            group["n"] += 1
            group["valid"] += data["evaluation_valid"]
            if data["evaluation_valid"]:
                group["eligible"] += data["eligible"]
                group["ineligible"] += not data["eligible"]
                group["released"] += data["released"]
                for key2 in ("false_release", "false_rejection", "safe_withhold",
                             "released_task_success", "released_safe_narrowing"):
                    group[key2] += data[key2]
    summary = {
        "phase": manifest["phase"], "planned_units": len(order), "completed_units": len(rows),
        "execution_failures": failure_count, "groups": groups,
        "usage": {k: sum(r["usage"].get(k, 0) for r in rows)
                  for k in ("prompt_tokens", "completion_tokens", "calls")},
        "interpretation": "Descriptive controlled-task benchmark; repetitions are not independent tasks.",
    }
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run", "summary"))
    parser.add_argument("--study", required=True)
    parser.add_argument("--phase", choices=("development", "formal"), default="development")
    parser.add_argument("--development")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args()
    study = Path(args.study).resolve()
    if args.command == "prepare":
        prepare(study, args.phase, args.development)
        return
    if args.command == "run":
        verify_freeze(study)
        if not 1 <= args.workers <= 4:
            raise ValueError("use 1..4 isolated worker processes")
        order = read(study / "run_order.json")
        environments = read(study / "private_environments.json")
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(execute_one, study, row, environments[row["case_id"]])
                       for row in order]
            for future in as_completed(futures):
                future.result()
        if not (study / "summary.json").exists():
            write_new(study / "summary.json", summarize(study))
    print(json.dumps(summarize(study), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
