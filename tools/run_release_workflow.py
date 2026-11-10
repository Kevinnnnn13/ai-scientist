"""Run one isolated full workflow on a prepared source packet.

Use a fresh process and output directory for EVERY run. Without --execute this
only checks inputs; --development marks results as non-formal.
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from evaluate_release_case import read_input


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--controller", choices=("A", "C"), required=True)
    parser.add_argument("--output", help="a NEW output directory")
    parser.add_argument("--repeat", type=int, choices=(1, 2, 3), default=1)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    spec, _base_candidate, corpus, policy = read_input(args.input, args.development)
    if spec["variant"] not in ("T0", "T5"):
        raise ValueError("full workflow matrix uses T0 and T5 only")
    summary = {
        "question_id": spec["question_id"], "variant": spec["variant"],
        "controller": args.controller, "repeat": args.repeat,
        "phase": "development" if args.development else "formal",
        "corpus_sha256": corpus.digest, "policy_sha256": policy.digest,
        "eligibility": "pending_human_review",
    }
    if not args.execute:
        print(json.dumps({"status": "input_checked", **summary}, indent=2))
        return 0
    if not args.output:
        raise ValueError("--execute requires a new --output directory")
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.environ["AI_LOG_DIR"] = str(output / "agent")
    os.environ["PROGRESS_FILE"] = str(output / "progress.json")
    os.environ["PYTHONIOENCODING"] = "utf-8"
    started = time.monotonic()
    exit_code = 0
    try:
        import langgraph_agent
        import llm_client
        from release_study_runtime import install, authorized_text
        counters = install(langgraph_agent, corpus, policy, args.controller,
                           judge_override=spec["variant"] == "T5", output=output)
        summary["model"] = llm_client.active_model()
        quality = {70: "\u4e00\u822c", 80: "\u597d", 90: "\u8d85\u597d", 92: "\u9876\u7ea7"}
        if policy.target not in quality:
            raise ValueError("target has no existing CLI quality mapping")
        sys.argv = [sys.argv[0], spec["question"], "--quality", quality[policy.target]]
        try:
            langgraph_agent.main()
        except SystemExit as exc:
            exit_code = int(exc.code or 0)
        states = list((output / "agent").rglob("state.json"))
        if len(states) != 1:
            raise RuntimeError("expected exactly one terminal state, got %d" % len(states))
        state = json.loads(states[0].read_text(encoding="utf-8"))
        if args.controller == "C" and state.get("plan_status") == "validated":
            if not authorized_text(state, policy, corpus):
                raise RuntimeError("saved release does not match its authorization")
        summary.update({
            "terminal_state_saved": True, "state_path": str(states[0]),
            "plan_status": state.get("plan_status", "in_progress"),
            "release_reason": state.get("release_reason", ""),
            "api_usage": llm_client.get_usage(), "runtime_counts": counters,
            "approved_plan_sha256": ((state.get("release_authorization") or {}).get("plan_sha256")
                                     if state.get("plan_status") == "validated" else None),
            "checked_plan_sha256": (state.get("release_authorization") or {}).get("plan_sha256"),
            "judge_intervention_applied": bool(counters["review_overrides"]),
        })
        if spec["variant"] == "T5" and not counters["review_overrides"]:
            summary["intervention_status"] = "not_applied"
        else:
            summary["intervention_status"] = "applied" if spec["variant"] == "T5" else "not_applicable"
    except Exception:
        exit_code = exit_code or 3
        summary["error"] = traceback.format_exc()
        summary.setdefault("terminal_state_saved", bool(list((output / "agent").rglob("state.json"))))
    summary.update({"exit_code": exit_code, "process_completed": exit_code == 0,
                    "seconds": time.monotonic() - started})
    with (output / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2)
    print(json.dumps({"output": str(output), "exit_code": exit_code}))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
