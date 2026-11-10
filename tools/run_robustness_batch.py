# -*- coding: utf-8 -*-
"""Run a reproducibility matrix for robustness experiments.

The runner writes a frozen run plan before contacting any model or search
service. Each run gets its own directory, condition config, logs, and state.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import time


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
PY = sys.executable


def _safe_name(value):
    text = str(value or "").strip()
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("._")[:80] or "item"


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with io.open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _read_json(path):
    with io.open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def _stable_id(*parts):
    raw = "|".join(str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _load_questions(path, fallback):
    if not path:
        return fallback
    with io.open(path, "r", encoding="utf-8-sig") as f:
        if path.lower().endswith(".json"):
            data = json.load(f)
            if isinstance(data, dict):
                return data.get("questions") or []
            return data if isinstance(data, list) else []
        questions = []
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                questions.append({"id": "q%02d" % (len(questions) + 1), "text": line})
        return questions


def _build_plan(config, repeat_override=None):
    experiment_id = str(config.get("experiment_id") or "robustness")
    questions = config.get("questions") or []
    conditions = config.get("conditions") or []
    quality = str(config.get("quality") or "超好")
    rows = []
    for question in questions:
        qid = str(question.get("id") or "q")
        for condition in conditions:
            cid = str(condition.get("id") or "condition")
            repeats = int(condition.get("repeats", 1) or 1)
            if repeat_override is not None:
                repeats = max(1, int(repeat_override))
            for repeat in range(1, repeats + 1):
                run_id = "%s__%s__%s__r%02d" % (
                    _safe_name(experiment_id), _safe_name(qid), _safe_name(cid), repeat
                )
                rows.append({
                    "run_id": run_id,
                    "experiment_id": experiment_id,
                    "question_id": qid,
                    "domain": question.get("domain") or "",
                    "question": question.get("text") or "",
                    "condition_id": cid,
                    "system": condition.get("system") or "F0",
                    "repeat": repeat,
                    "quality": quality,
                    "perturbations": condition.get("perturbations") or [],
                })
    return rows


def _write_plan_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fields = [
        "run_id", "experiment_id", "question_id", "domain", "condition_id",
        "system", "repeat", "quality", "question", "perturbations",
    ]
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["perturbations"] = json.dumps(out.get("perturbations") or [], ensure_ascii=False)
            writer.writerow(out)


def _find_state(run_dir):
    for root, _dirs, files in os.walk(run_dir):
        if "state.json" in files:
            path = os.path.join(root, "state.json")
            try:
                return path, _read_json(path)
            except Exception:
                continue
    return None, None


def _read_tail(path, n=20):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception:
        return ""


def _git_snapshot():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip()
        dirty = bool(subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        ).strip())
        return commit, dirty
    except Exception:
        return "", None


def _execute_row(row, output_root, timeout):
    run_dir = os.path.join(output_root, "runs", row["run_id"])
    os.makedirs(run_dir, exist_ok=True)
    git_commit, git_dirty = _git_snapshot()
    condition = {
        "condition_id": row["condition_id"],
        "system": row["system"],
        "perturbations": row["perturbations"],
    }
    _write_json(os.path.join(run_dir, "condition.json"), condition)
    _write_json(os.path.join(run_dir, "question.json"), {
        "question_id": row["question_id"],
        "domain": row["domain"],
        "question": row["question"],
    })
    _write_json(os.path.join(run_dir, "metadata.json"), {
        "run_id": row["run_id"],
        "experiment_id": row["experiment_id"],
        "condition_id": row["condition_id"],
        "system": row["system"],
        "question_id": row["question_id"],
        "domain": row["domain"],
        "repeat": row["repeat"],
        "quality": row["quality"],
        "started": time.time(),
        "python": sys.version,
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "model_backend": os.getenv("LLM_BACKEND", "deepseek"),
        "model_name": (
            os.getenv("DEEPSEEK_MODEL")
            or os.getenv("QWEN_MODEL")
            or ("qwen-plus" if os.getenv("LLM_BACKEND", "").lower() == "qwen"
                else ("deepseek-chat" if os.getenv("LLM_BACKEND", "").lower() == "deepseek"
                      else os.getenv("OLLAMA_MODEL", "")))
        ),
        "perturbations": row["perturbations"],
    })

    agent_output = os.path.join(run_dir, "agent_output")
    os.makedirs(agent_output, exist_ok=True)
    run_log = os.path.join(run_dir, "run.log")
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["AI_LOG_DIR"] = agent_output
    env["PROGRESS_FILE"] = os.path.join(agent_output, "_progress.json")
    env["ROBUSTNESS_CONFIG"] = os.path.join(run_dir, "condition.json")
    env["ROBUSTNESS_SYSTEM"] = row["system"]
    env["ROBUSTNESS_AUDIT_FILE"] = os.path.join(run_dir, "hook_audit.jsonl")
    cmd = [
        PY,
        os.path.join(ROOT, "tools", "run_agent_condition.py"),
        row["question"],
        "--system", row["system"],
        "--robustness-config", env["ROBUSTNESS_CONFIG"],
        "--quality", row["quality"],
    ]
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout,
        )
        exit_code = proc.returncode
        output = proc.stdout or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        output = exc.stdout or ""
        timed_out = True
    with io.open(run_log, "w", encoding="utf-8") as f:
        f.write(output)
    state_path, state = _find_state(run_dir)
    result = {
        "run_id": row["run_id"],
        "condition_id": row["condition_id"],
        "system": row["system"],
        "question_id": row["question_id"],
        "domain": row["domain"],
        "repeat": row["repeat"],
        "exit_code": exit_code,
        "timed_out": timed_out,
        "seconds": round(time.time() - started, 2),
        "state_path": state_path,
        "run_log": run_log,
        "ok": exit_code == 0 and isinstance(state, dict),
        "error_tail": _read_tail(run_log) if exit_code != 0 else "",
    }
    lower_error = str(result["error_tail"] or "").lower()
    external_markers = (
        "free quota exhausted", "insufficient_quota", "permissiondeniederror",
        "invalid_api_key", "authenticationerror", "allocationquota",
    )
    result["external_api_failure"] = int(any(marker in lower_error for marker in external_markers))
    if result["external_api_failure"]:
        result["error_class"] = "external_api_failure"
    elif result["timed_out"]:
        result["error_class"] = "timeout"
    elif exit_code != 0:
        result["error_class"] = "process_failure"
    if isinstance(state, dict):
        for key in (
            "best_score", "best_data_score", "plan_status", "evidence_status",
            "release_reason", "anchor_blocked", "anchor_issues", "retrieval_error",
            "generation_error", "api_usage", "api_cost_cny", "question", "system",
        ):
            if key in state:
                result[key] = state[key]
        result["literature_count"] = len(state.get("literature") or [])
        result["hypothesis_chars"] = len(str(state.get("best_hypothesis") or ""))
    _write_json(os.path.join(run_dir, "result.json"), result)
    return result


def main():
    parser = argparse.ArgumentParser(description="Run robustness experiment matrix")
    parser.add_argument("--config", required=True, help="experiment JSON config")
    parser.add_argument("--questions", default="", help="optional question JSON/txt override")
    parser.add_argument("--output", default="", help="output directory")
    parser.add_argument("--quality", default="", help="override quality")
    parser.add_argument("--condition", default="", help="only run this condition id")
    parser.add_argument(
        "--conditions",
        default="",
        help="comma-separated condition ids to run",
    )
    parser.add_argument("--question", default="", help="only run this question id")
    parser.add_argument("--repeat-override", type=int, default=None)
    parser.add_argument("--max-runs", type=int, default=0, help="0 means no limit")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    config = _read_json(config_path)
    if args.questions:
        config["questions"] = _load_questions(args.questions, config.get("questions") or [])
    if args.quality:
        config["quality"] = args.quality
    rows = _build_plan(config, args.repeat_override)
    if args.condition:
        rows = [row for row in rows if row["condition_id"] == args.condition]
    if args.conditions:
        wanted = {
            item.strip()
            for item in str(args.conditions).split(",")
            if item.strip()
        }
        rows = [row for row in rows if row["condition_id"] in wanted]
    if args.question:
        rows = [row for row in rows if row["question_id"] == args.question]
    if args.max_runs > 0:
        rows = rows[:args.max_runs]

    output_root = args.output or os.path.join(
        ROOT, "robustness_runs",
        "%s_%s" % (_safe_name(config.get("experiment_id") or "experiment"),
                   time.strftime("%Y%m%d_%H%M%S")),
    )
    output_root = os.path.abspath(output_root)
    os.makedirs(output_root, exist_ok=True)
    _write_plan_csv(os.path.join(output_root, "run_plan.csv"), rows)
    _write_json(os.path.join(output_root, "run_plan.json"), rows)
    print("planned_runs=%d output=%s" % (len(rows), output_root))
    if args.dry_run:
        return 0

    progress = {
        "total": len(rows),
        "done": 0,
        "ok": 0,
        "fail": 0,
        "started": time.time(),
        "current": None,
        "items": [],
    }
    _write_json(os.path.join(output_root, "_progress.json"), progress)
    for index, row in enumerate(rows, 1):
        result_path = os.path.join(output_root, "runs", row["run_id"], "result.json")
        if args.resume and os.path.isfile(result_path):
            try:
                result = _read_json(result_path)
                # Re-run infrastructure failures such as exhausted API quota;
                # keep completed runs even when the perturbation caused a
                # controlled non-zero exit.
                if result.get("state_path") and not result.get("external_api_failure"):
                    progress["items"].append(result)
                    progress["done"] = index
                    progress["ok"] += 1 if result.get("ok") else 0
                    progress["fail"] += 0 if result.get("ok") else 1
                    _write_json(os.path.join(output_root, "_progress.json"), progress)
                    print("[%d/%d] skip existing %s" % (index, len(rows), row["run_id"]))
                    continue
            except Exception:
                pass

        progress["current"] = {
            "index": index,
            "run_id": row["run_id"],
            "condition_id": row["condition_id"],
            "question_id": row["question_id"],
        }
        _write_json(os.path.join(output_root, "_progress.json"), progress)
        print("[%d/%d] %s | %s | %s" % (
            index, len(rows), row["run_id"], row["condition_id"], row["question_id"]
        ))
        result = _execute_row(row, output_root, args.timeout)
        progress["items"].append(result)
        progress["done"] = index
        progress["ok"] += 1 if result.get("ok") else 0
        progress["fail"] += 0 if result.get("ok") else 1
        progress["current"] = None
        _write_json(os.path.join(output_root, "_progress.json"), progress)
        print("[%d/%d] %s status=%s seconds=%s" % (
            index, len(rows), "OK" if result.get("ok") else "FAIL",
            result.get("plan_status"), result.get("seconds"),
        ))

    progress["finished"] = time.time()
    _write_json(os.path.join(output_root, "_summary.json"), progress)
    print("finished ok=%d fail=%d output=%s" % (
        progress["ok"], progress["fail"], output_root
    ))
    return 0 if progress["fail"] == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
