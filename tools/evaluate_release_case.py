"""Replay A/B/C on an identical, hash-checked plan. Default is a dry run.

This tool produces decisions, never scientific correctness labels. Formal
evaluation is intentionally gated on independently reviewed materials.
"""

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController


def read_input(path, development=False):
    path = Path(path).resolve()
    spec = json.loads(path.read_text(encoding="utf-8-sig"))
    if spec.get("schema_version") != 1:
        raise ValueError("unsupported case schema")
    if not development:
        if spec.get("material_status") != "independently_reviewed":
            raise ValueError("formal execution requires independently reviewed materials")
        provenance = spec.get("provenance", {})
        records = provenance.get("independent_review_records", [])
        if provenance.get("source_checks") != "complete" or len(records) < 2:
            raise ValueError("source checks and two independent review records are required")
        if len({record.get("reviewer_id") for record in records}) < 2:
            raise ValueError("independent reviewers must have distinct recorded IDs")
        for record in records:
            if not record.get("reviewer_id") or not record.get("record_sha256"):
                raise ValueError("review provenance is incomplete")
        if not spec.get("freeze_manifest"):
            raise ValueError("a final code/model/material freeze is required")
        freeze_path = (path.parent / spec["freeze_manifest"]).resolve()
        freeze = json.loads(freeze_path.read_text(encoding="utf-8-sig"))
        if freeze.get("status") != "frozen" or not freeze.get("model_snapshot"):
            raise ValueError("final model freeze is incomplete")
        for relative, digest in freeze.get("code", {}).items():
            code = (ROOT / relative).resolve()
            if ROOT not in code.parents or hashlib.sha256(code.read_bytes()).hexdigest() != digest:
                raise ValueError("code differs from the frozen snapshot")
        required = {"src/selective_release.py", "src/release_study_runtime.py",
                    "src/langgraph_agent.py", "src/llm_client.py",
                    "tools/evaluate_release_case.py", "tools/run_release_workflow.py"}
        if not required.issubset(freeze.get("code", {})):
            raise ValueError("freeze omits required code files")
        if freeze.get("policy") != spec["policy"]:
            raise ValueError("policy differs from the frozen version")
    plan_path = (path.parent / spec["plan_path"]).resolve()
    raw = plan_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != spec["plan_sha256"]:
        raise ValueError("candidate plan differs from its frozen SHA-256")
    corpus = Corpus.load((path.parent / spec["corpus_path"]).resolve(), spec["corpus_sha256"])
    policy = ReleasePolicy(**spec["policy"])
    review = spec["review"]
    candidate = Candidate(raw.decode("utf-8-sig"), review["hypothesis_score"],
                          review["data_score"], review["dimensions"],
                          spec.get("retrieved_instruction", ""))
    if spec.get("passed_override") is not None and type(spec["passed_override"]) is not bool:
        raise ValueError("passed_override must be a boolean or null")
    if not development:
        frozen_inputs = freeze.get("materials", {})
        for name, digest in ((spec["plan_path"], spec["plan_sha256"]),
                             (spec["corpus_path"], spec["corpus_sha256"])):
            key = str((path.parent / name).resolve())
            if frozen_inputs.get(key) != digest:
                raise ValueError("material is absent from final freeze: " + name)
        from selective_release import canonical_hash
        if freeze.get("cases", {}).get(str(path)) != canonical_hash(spec):
            raise ValueError("case settings are absent from or differ from final freeze")
        snapshot = freeze["model_snapshot"]
        if (not isinstance(snapshot, dict)
                or not all(snapshot.get(key) for key in ("backend", "name", "access_date"))):
            raise ValueError("model snapshot needs backend, name and access_date")
        import os
        import llm_client
        if (os.getenv("LLM_BACKEND", "deepseek").lower() != snapshot["backend"]
                or llm_client.active_model() != snapshot["name"]):
            raise ValueError("active model does not match the frozen backend/name")
    return spec, candidate, corpus, policy


def compare(candidate, corpus, policy, verifier, passed_override=None):
    import anchor_checker
    import langgraph_agent
    from robustness_hooks import apply_downgrade_only
    if (policy.dimension_floor != langgraph_agent.floor_for(policy.target)
            or policy.novelty_floor != langgraph_agent.novelty_floor_for(policy.target)
            or policy.evidence_floor != 60):
        raise ValueError("A and C quality policies must match")
    state = {
        "quality_target": policy.target,
        "hypothesis_score": candidate.hypothesis_score,
        "data_score": candidate.evidence_score,
        "dimensions": candidate.dimensions,
        "anchor_blocked": bool(anchor_checker.check_hypothesis(candidate.text)),
    }
    legacy = langgraph_agent.assess_plan_release(state, passed=passed_override)
    blocked = apply_downgrade_only(*legacy)
    report = {}
    for arm, values in (("A", legacy), ("B", blocked)):
        report[arm] = dict(zip(("plan_status", "evidence_status", "release_reason"), values))
    report["C"] = SelectiveController(corpus, verifier, policy).assess(candidate)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", help="NEW JSON result path; required for --execute")
    parser.add_argument("--execute", action="store_true", help="call the configured evidence-verifier API")
    parser.add_argument("--development", action="store_true", help="non-formal development data only")
    args = parser.parse_args()
    spec, candidate, corpus, policy = read_input(args.input, args.development)
    summary = {
        "question_id": spec["question_id"], "variant": spec["variant"],
        "study_phase": "development" if args.development else "formal",
        "plan_sha256": spec["plan_sha256"], "corpus_sha256": spec["corpus_sha256"],
        "policy": asdict(policy), "status": "input_checked", "eligibility": "pending_human_review",
    }
    if not args.execute:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if not args.output or Path(args.output).exists():
        raise ValueError("--execute requires a new output path")
    import llm_client
    import os
    verifier = llm_client.json_chat
    summary["model"] = {"backend": os.getenv("LLM_BACKEND", "deepseek"),
                        "name": llm_client.active_model()}
    before = dict(llm_client.get_usage())
    started = time.monotonic()
    result = compare(candidate, corpus, policy, verifier, spec.get("passed_override"))
    after = llm_client.get_usage()
    summary.update({"status": "completed", "decisions": result,
                    "seconds": time.monotonic() - started,
                    "usage_delta": {key: after.get(key, 0) - before.get(key, 0)
                                    for key in ("prompt_tokens", "completion_tokens", "calls")}})
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(summary, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"output": str(output), "status": summary["status"]}))


if __name__ == "__main__":
    main()
