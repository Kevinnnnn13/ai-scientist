"""Two live verifier integration checks on explicitly synthetic development data."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController


def integration_passed(decision, expected):
    errors = decision.get("errors", [])
    usable = decision.get("evidence_check") in ("passed", "not_authorized")
    well_formed = not any(error.startswith("invalid_verification_receipt:")
                          for error in errors)
    return usable and well_formed and decision.get("plan_status") == expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="NEW result JSON file")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print("Dry run: two synthetic development inputs; no model calls.")
        return 0
    output = Path(args.output)
    if output.exists():
        raise FileExistsError("do not overwrite a previous development check")
    import llm_client
    backend = os.getenv("LLM_BACKEND", "deepseek").lower()
    summary = {
        "phase": "development", "data_kind": "synthetic_integration_fixture",
        "not_formal_study_data": True, "model": llm_client.active_model(),
        "backend": backend, "checks": [],
    }
    before = llm_client.get_usage()
    started = time.monotonic()
    policy = ReleasePolicy()
    plan = (
        "The supplied fictional source reports a signal increase under its stated measurement conditions (Figure 2).\n"
        "We propose to test whether the effect persists under a new measurement condition."
    )
    candidate = Candidate(plan, 95, 85,
                          dict(testability=95, evidence=85, feasibility=90, novelty=80))
    for name, passage, expected in (
        ("positive_locator",
         "Figure 2 reports a signal increase under the stated measurement conditions.",
         "validated"),
        ("missing_support",
         "Figure 2 describes the instrument housing and contains no signal measurements.",
         "in_progress"),
    ):
        corpus = Corpus({
            "schema_version": 1,
            "sources": [{"id": "s1", "title": "Fictional integration-test source",
                         "origin": "synthetic://development-only",
                         "passages": [{"id": "p1", "locator": "Figure 2", "text": passage}]}],
        })
        decision = SelectiveController(corpus, llm_client.json_chat, policy).assess(candidate)
        usable = decision["evidence_check"] not in ("not_evaluated", "unavailable")
        summary["checks"].append({
            "check": name, "expected_for_fixture": expected, "decision": decision,
            "integration_passed": integration_passed(decision, expected),
        })
        if not usable:
            break
    after = llm_client.get_usage()
    summary.update({
        "seconds": time.monotonic() - started,
        "api_usage_delta": {key: after.get(key, 0) - before.get(key, 0)
                            for key in ("prompt_tokens", "completion_tokens", "calls")},
        "all_passed": len(summary["checks"]) == 2 and all(
            row["integration_passed"] for row in summary["checks"]),
    })
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"output": str(output), "all_passed": summary["all_passed"],
                      "api_usage_delta": summary["api_usage_delta"]}))
    return 0 if summary["all_passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
