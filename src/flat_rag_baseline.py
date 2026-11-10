# -*- coding: utf-8 -*-
"""Flat retrieval-augmented baseline used by robustness experiments.

This baseline performs one retrieval pass followed by one structured
generation call. It does not use the multi-stage knowledge tree, review
loop, hard anchors, or release gate.
"""

import argparse
import io
import json
import os
import sys
import time


SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

import llm_client
import search_papers


PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "evidence": {"type": "string"},
                    "confidence": {"type": "string"},
                },
                "required": ["claim", "evidence", "confidence"],
            },
        },
        "uncertainty": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "claims", "uncertainty", "citations"],
}


def _format_papers(papers):
    lines = []
    for i, paper in enumerate(papers or [], 1):
        title = paper.get("标题") or paper.get("title") or "Untitled"
        year = paper.get("年份") or paper.get("year") or ""
        doi = paper.get("DOI") or paper.get("doi") or ""
        lines.append("[%d] %s (%s) DOI=%s" % (i, title, year, doi))
        if paper.get("摘要"):
            lines.append("    %s" % paper["摘要"])
    return "\n".join(lines) or "(no retrieved evidence)"


def _safe_json(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def run(question, quality="超好"):
    log_dir = os.getenv("AI_LOG_DIR") or os.path.join(SRC, "logs", "flat_rag")
    day_dir = os.path.join(log_dir, time.strftime("%Y-%m-%d"))
    run_folder = os.path.join(
        day_dir, "运行01_flat_rag_%s" % time.strftime("%Y%m%d_%H%M%S")
    )
    os.makedirs(run_folder, exist_ok=True)

    retrieval_error = ""
    literature = []
    try:
        raw = search_papers.search_papers(question, per_page=6)
        literature = [search_papers.paper_to_dict(paper) for paper in raw]
    except Exception as exc:
        retrieval_error = "%s: %s" % (type(exc).__name__, exc)

    prompt = """Research question:
%s

Retrieved evidence:
%s

Retrieval error:
%s

Produce one concise research plan. Use only the retrieved evidence.
If the evidence is missing, conflicting, or not verifiable, say so explicitly.
Do not claim that an experiment was already performed. Return JSON only.
""" % (question, _format_papers(literature), retrieval_error or "(none)")

    system = (
        "You are a flat retrieval-augmented research-planning baseline. "
        "Return strict JSON. Do not invent citations."
    )
    plan = {}
    generation_error = ""
    try:
        plan = llm_client.json_chat(
            prompt, system=system, schema=PLAN_SCHEMA, max_retries=2
        )
    except Exception as exc:
        generation_error = "%s: %s" % (type(exc).__name__, exc)
        plan = {
            "summary": "",
            "claims": [],
            "uncertainty": "Generation failed: %s" % generation_error,
            "citations": [],
        }

    final_text = _safe_json(plan)
    state = {
        "question": question,
        "quality_target": quality,
        "system": "B1_flat_rag",
        "status": "error" if generation_error and not plan.get("summary") else "完成",
        "best_hypothesis": final_text,
        "best_score": None,
        "best_data_score": None,
        "plan_status": "ungated",
        "evidence_status": "not_gated",
        "release_reason": (
            "Flat RAG baseline has no release gate. "
            + ("Retrieval error: %s. " % retrieval_error if retrieval_error else "")
            + ("Generation error: %s. " % generation_error if generation_error else "")
        ).strip(),
        "anchor_blocked": None,
        "anchor_issues": [],
        "literature": literature,
        "retrieval_error": retrieval_error,
        "generation_error": generation_error,
        "final_answer": final_text,
        "run_folder": run_folder,
        "api_usage": llm_client.get_usage(),
    }
    state_path = os.path.join(run_folder, "state.json")
    with io.open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    with io.open(os.path.join(run_folder, "05_最终交付.md"), "w", encoding="utf-8") as f:
        f.write(final_text + "\n")
    with io.open(os.path.join(run_folder, "run.log"), "w", encoding="utf-8") as f:
        f.write("question: %s\n" % question)
        f.write("retrieval_count: %d\n" % len(literature))
        f.write("retrieval_error: %s\n" % (retrieval_error or "(none)"))
        f.write("generation_error: %s\n" % (generation_error or "(none)"))
    print("[flat-rag] state: %s" % state_path)
    return state


def main():
    parser = argparse.ArgumentParser(description="Flat retrieval-augmented baseline")
    parser.add_argument("question")
    parser.add_argument("--quality", default="超好")
    args = parser.parse_args()
    state = run(args.question, args.quality)
    return 0 if state.get("status") != "error" else 3


if __name__ == "__main__":
    sys.exit(main())
