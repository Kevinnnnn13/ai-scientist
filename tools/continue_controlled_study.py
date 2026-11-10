"""Audited orchestration for the frozen v2 worker and independent scorer.

The original scientific code and materials stay frozen. Only unfinished units
may receive a new attempt directory. Completed outcomes are never rerun here.
"""

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

from run_programmatic_release import (
    ROOT, digest, read, score_result, summarize, verify_freeze, write_new,
)
from selective_release import canonical_hash


HARNESS_VERSION = "controlled-resume-v1.1"
HARNESS_FILES = ("tools/continue_controlled_study.py", "tests/test_controlled_resume.py",
                 "docs/programmatic_release_execution_addendum_20261015.md")


def result_path(study, scored):
    relative = scored.get("result_path", "runs/" + scored["unit_id"] + "/result.json")
    path = (study / relative).resolve()
    if study.resolve() not in path.parents:
        raise ValueError("result path escapes study")
    if digest(path) != scored["result_sha256"]:
        raise ValueError("saved result checksum mismatch")
    return path


def choose_attempt(study, unit, allow_interrupted):
    """Never replace existing output; completed but unscored results are reused."""
    base = study / "runs" / unit
    attempts = [base] + sorted((study / "attempts" / unit).glob("attempt_*"))
    for path in attempts:
        if (path / "result.json").exists():
            return path, []
    incomplete = [path for path in attempts if path.exists()]
    if not incomplete:
        return base, []
    if not allow_interrupted:
        raise RuntimeError("unfinished attempt needs explicit resume: " + unit)
    number = len(attempts) + 1
    target = study / "attempts" / unit / ("attempt_%03d" % number)
    return target, [path.relative_to(study).as_posix() for path in incomplete]


def check_saved_score(study, row, environment):
    scored = read(study / "scored" / (row["unit_id"] + ".json"))
    result = read(result_path(study, scored))
    expected = score_result(result, environment)
    if scored["truth"] != expected["truth"] or scored["arms"] != expected["arms"]:
        raise ValueError("saved score disagrees with frozen oracle: " + row["unit_id"])
    for key, value in row.items():
        if scored.get(key) != value:
            raise ValueError("saved score disagrees with run order")
    payload = read(study / "inputs" / (row["unit_id"] + ".json"))
    if result.get("public_input_sha256") != canonical_hash(payload):
        raise ValueError("saved result is not bound to this public input")
    return scored


def execute_unit(study, row, environment, allow_interrupted):
    unit = row["unit_id"]
    scored_path = study / "scored" / (unit + ".json")
    if scored_path.exists():
        return check_saved_score(study, row, environment)
    output, interrupted = choose_attempt(study, unit, allow_interrupted)
    output.parent.mkdir(parents=True, exist_ok=True)
    result_file = output / "result.json"
    process_code = None
    if not result_file.exists():
        logs = study / "resume_logs"
        logs.mkdir(exist_ok=True)
        name = unit + "_" + output.name
        write_new(logs / (name + "_launch.json"), {
            "unit_id": unit, "started_utc": datetime.now(timezone.utc).isoformat(),
            "output_path": output.relative_to(study).as_posix(),
            "preserved_interrupted_attempts": interrupted,
            "interrupted_remote_usage": "unknown; not a defense outcome",
        })
        env = dict(os.environ, PYTHONIOENCODING="utf-8",
                   PYTHONDONTWRITEBYTECODE="1", LLM_BACKEND="deepseek")
        try:
            with (logs / (name + ".txt")).open("x", encoding="utf-8") as log:
                completed = subprocess.run(
                    [sys.executable, "-B", "-X", "utf8",
                     str(ROOT / "tools/programmatic_release_worker.py"),
                     "--input", str(study / "inputs" / (unit + ".json")),
                     "--output", str(output)],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=1200, check=False,
                )
                process_code = completed.returncode
        except subprocess.TimeoutExpired:
            output.mkdir(parents=True, exist_ok=True)
            if not result_file.exists():
                write_new(result_file, {"status": "process_timeout",
                                       "decisions": {}, "artifact": None})
    if not result_file.exists():
        output.mkdir(parents=True, exist_ok=True)
        write_new(result_file, {"status": "process_error", "exit_code": process_code,
                               "decisions": {}, "artifact": None})
    result = read(result_file)
    payload = read(study / "inputs" / (unit + ".json"))
    if result["status"] == "completed" and result.get("public_input_sha256") != canonical_hash(payload):
        raise ValueError("worker result has a different public input")
    scored = {
        **row, "result_path": result_file.relative_to(study).as_posix(),
        "result_sha256": digest(result_file), "status": result["status"],
        "seconds": result.get("seconds"), "usage": result.get("usage", {}),
        "rounds": result.get("rounds"), **score_result(result, environment),
    }
    write_new(scored_path, scored)
    print(json.dumps({
        "unit": unit, "case": row["case_id"], "kind": row["kind"],
        "status": result["status"], "arms": {
            arm: {"release": data["released"], "eligible": data["eligible"],
                  "valid": data["evaluation_valid"]}
            for arm, data in scored["arms"].items()},
    }), flush=True)
    return scored


def freeze_harness(study, manifest):
    document = {
        "version": HARNESS_VERSION, "base_manifest_sha256": digest(study / "manifest.json"),
        "code": {path: digest(ROOT / path) for path in HARNESS_FILES},
        "changes": "orchestration only; controller, prompts, materials and scorer unchanged",
    }
    path = study / "execution_manifest.json"
    if path.exists():
        if read(path) != document:
            raise ValueError("orchestration changed after its first execution freeze")
    else:
        write_new(path, document)
    archive = study / "frozen_source.zip"
    if not archive.exists():
        with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED) as zipped:
            for relative in sorted(set(manifest["code"]) | set(HARNESS_FILES)):
                zipped.write(ROOT / relative, relative)
    return digest(path)


def run_batch(study, workers, allow_interrupted):
    manifest = verify_freeze(study)
    for package, version in manifest["packages"].items():
        if importlib.metadata.version(package) != version:
            raise ValueError("dependency differs from freeze: " + package)
    execution_hash = freeze_harness(study, manifest)
    order = read(study / "run_order.json")
    environments = read(study / "private_environments.json")
    pending = []
    for row in order:
        if (study / "scored" / (row["unit_id"] + ".json")).exists():
            check_saved_score(study, row, environments[row["case_id"]])
        else:
            choose_attempt(study, row["unit_id"], allow_interrupted)
            pending.append(row)
    sessions = study / "execution_sessions"
    sessions.mkdir(exist_ok=True)
    session_path = sessions / ("%03d.json" % (len(list(sessions.glob("*.json"))) + 1))
    write_new(session_path, {
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "execution_manifest_sha256": execution_hash, "workers": workers,
        "remaining_units": [r["unit_id"] for r in pending],
        "allow_interrupted": allow_interrupted,
        "authorization": "User requested continuing work on 2026-10-15.",
    })
    stop_path = study / "STOP_REQUESTED"
    iterator = iter(pending)
    # Keep only workers-sized outstanding work so STOP_REQUESTED halts dispatch.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        active = {}

        def dispatch():
            while len(active) < workers and not stop_path.exists():
                row = next(iterator, None)
                if row is None:
                    break
                future = pool.submit(execute_unit, study, row,
                                     environments[row["case_id"]], allow_interrupted)
                active[future] = row["unit_id"]

        dispatch()
        while active:
            done, _ = wait(active, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                valid = result["status"] == "completed" and all(
                    arm["evaluation_valid"] for arm in result["arms"].values())
                if not valid and not stop_path.exists():
                    with stop_path.open("x", encoding="utf-8") as stream:
                        stream.write("Automatic drain after an execution/protocol failure in "
                                     + active[future] + ". Preserve failure before retrying.\n")
                del active[future]
            dispatch()
    summary = summarize(study)
    if summary["completed_units"] == summary["planned_units"] and not (study / "summary.json").exists():
        write_new(study / "summary.json", summary)
    snapshot = study / ("summary_session_" + session_path.stem + ".json")
    write_new(snapshot, summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=3)
    parser.add_argument("--resume-interrupted", action="store_true")
    args = parser.parse_args()
    run_batch(Path(args.study).resolve(), args.workers, args.resume_interrupted)


if __name__ == "__main__":
    main()
