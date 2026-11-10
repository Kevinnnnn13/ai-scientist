"""Model-side worker: accepts public inputs only and never imports the oracle."""

import argparse
import copy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from programmatic_release_tasks import (
    ARTIFACT_SCHEMA, GENERATOR_SYSTEM, REVIEW_SCHEMA, REVIEW_SYSTEM, render, review_input,
)
from selective_release import Candidate, Corpus, ReleasePolicy, SelectiveController, canonical_hash


def emit(path, value):
    with Path(path).open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")


def ensure_shape(artifact):
    """Strict output contract, without deciding scientific/evidence eligibility."""
    import jsonschema
    jsonschema.validate(artifact, ARTIFACT_SCHEMA)
    if artifact["value"] is not None and not math.isfinite(artifact["value"]):
        raise ValueError("nonfinite value")
    if (artifact["mode"] == "result") != (artifact["value"] is not None):
        raise ValueError("mode/value mismatch")
    if len(set(artifact["citations"])) != len(artifact["citations"]):
        raise ValueError("duplicate citations")


def usable_decision(decision):
    return (decision.get("evidence_check") != "unavailable"
            and not any("invalid_verification_receipt:" in e
                        for e in decision.get("errors", [])))


def install_recording(client_module, trace):
    original = client_module.get_client

    def factory():
        client, model = original()
        client = client.with_options(timeout=120, max_retries=0)

        def create(**kwargs):
            start = time.monotonic()
            kwargs["max_tokens"] = 8192
            row = {"started_utc": datetime.now(timezone.utc).isoformat(), "request": kwargs}
            try:
                response = client.chat.completions.create(**kwargs)
                row.update(response=response.model_dump(mode="json"),
                           seconds=time.monotonic() - start, status="received")
                return response
            except Exception as exc:
                # Exception strings from HTTP clients can contain request details.
                row.update(status="api_error", error_type=type(exc).__name__,
                           seconds=time.monotonic() - start)
                raise
            finally:
                emit(trace, row)

        return SimpleNamespace(chat=SimpleNamespace(
            completions=SimpleNamespace(create=create))), model

    client_module.get_client = factory


def candidate(text, review, public):
    return Candidate(text, review["hypothesis_score"], review["data_score"],
                     copy.deepcopy(review["dimensions"]), public["retrieved_context"])


def assess_legacy(obj, passed=None):
    import anchor_checker
    import langgraph_agent
    state = {
        "quality_target": 90, "hypothesis_score": obj.hypothesis_score,
        "data_score": obj.evidence_score, "dimensions": obj.dimensions,
        "anchor_blocked": bool(anchor_checker.check_hypothesis(obj.text)),
    }
    values = langgraph_agent.assess_plan_release(state, passed=passed)
    return dict(zip(("plan_status", "evidence_status", "release_reason"), values))


def run(payload, json_chat, events):
    allowed = {"kind", "public", "initial_artifact", "override", "arm", "max_rounds"}
    if set(payload) != allowed:
        raise ValueError("worker accepts only the public experiment interface")
    public = payload["public"]
    if set(public) != {"operation", "question", "corpus", "retrieved_context"}:
        raise ValueError("unexpected private field in public input")
    corpus = Corpus(public["corpus"])
    policy = ReleasePolicy()
    controller = SelectiveController(corpus, json_chat, policy)
    if payload["kind"] == "component":
        ensure_shape(payload["initial_artifact"])
        text = render(payload["initial_artifact"], public["operation"])
        review = review_input(payload["override"])
        obj = candidate(text, review, public)
        a = assess_legacy(obj, True if payload["override"] else None)
        b = copy.deepcopy(a)
        if b["plan_status"] == "validated":
            b.update(plan_status="in_progress", evidence_status="withheld",
                     release_reason="Always withhold validated output.")
        c = controller.assess(obj)
        return {"artifact": payload["initial_artifact"], "rendered_text": text,
                "decisions": {"A": a, "B": b, "C": c}, "review_input": review,
                "status": "completed", "rounds": 1}
    if payload["kind"] != "workflow" or payload["arm"] not in ("A", "C"):
        raise ValueError("invalid workflow kind/arm")
    history, feedback = [], ""
    artifact, decision, text = None, None, ""
    for round_no in range(1, payload["max_rounds"] + 1):
        generation_input = {
            "task": public["question"], "available_sources": corpus.prompt_document(),
            "untrusted_retrieval_notes": public["retrieved_context"],
            "previous_artifact": artifact, "feedback": feedback,
        }
        artifact = json_chat(json.dumps(generation_input), system=GENERATOR_SYSTEM,
                             schema=ARTIFACT_SCHEMA, max_retries=1)
        ensure_shape(artifact)
        text = render(artifact, public["operation"])
        original = json_chat(json.dumps({
            "plan": text, "available_sources": corpus.prompt_document(),
            "untrusted_retrieval_notes": public["retrieved_context"],
        }), system=REVIEW_SYSTEM, schema=REVIEW_SCHEMA, max_retries=1)
        import jsonschema
        jsonschema.validate(original, REVIEW_SCHEMA)
        effective = review_input(True) if payload["override"] else original
        if payload["override"]:
            effective["feedback"] = "Reviewer recommends release."
        obj = candidate(text, effective, public)
        decision = (controller.assess(obj) if payload["arm"] == "C" else
                    assess_legacy(obj, True if payload["override"] else None))
        entry = {"round": round_no, "artifact": artifact, "rendered_text": text,
                 "original_review": original, "effective_review": effective,
                 "override_applied": payload["override"],
                 "candidate_sha256": canonical_hash({
                     "text": text, "review": effective, "corpus": corpus.digest}),
                 "decision": decision}
        history.append(entry)
        emit(events, entry)
        if not usable_decision(decision):
            return {"status": "verification_failure", "artifact": artifact,
                    "decisions": {payload["arm"]: decision}, "history": history,
                    "rounds": round_no, "rendered_text": text}
        if decision["plan_status"] == "validated":
            break
        feedback = effective["feedback"] + "\n" + decision["release_reason"]
    return {"status": "completed", "artifact": artifact, "rendered_text": text,
            "decisions": {payload["arm"]: decision}, "history": history,
            "rounds": len(history),
            "budget_exhausted": decision["plan_status"] != "validated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    os.environ["LLM_BACKEND"] = "deepseek"
    import llm_client
    if not os.getenv("DEEPSEEK_API_KEY", "").strip():
        raise ValueError("DeepSeek key is missing")
    install_recording(llm_client, output / "api_trace.jsonl")
    started = time.monotonic()
    before = llm_client.get_usage()
    try:
        result = run(payload, llm_client.json_chat, output / "rounds.jsonl")
    except Exception as exc:
        result = {"status": "worker_error", "error_type": type(exc).__name__,
                  "decisions": {}, "artifact": None}
        last = getattr(exc, "last_content", None)
        if last is not None:
            result["last_model_content"] = last
    after = llm_client.get_usage()
    result.update(
        model=llm_client.active_model(), backend="deepseek",
        seconds=time.monotonic() - started,
        usage={k: after[k] - before[k] for k in before},
        access_utc=datetime.now(timezone.utc).isoformat(),
        public_input_sha256=canonical_hash(payload),
    )
    with (output / "result.json").open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
    print(json.dumps({"status": result["status"], "seconds": result["seconds"],
                      "calls": result["usage"]["calls"]}), flush=True)
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
