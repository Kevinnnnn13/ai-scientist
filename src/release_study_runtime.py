"""Process-local integration for the new release study.

Installed only by its dedicated runner. Historical code and data are unchanged.
The trusted launcher owns the corpus, policy, verifier call and audit sink.
"""

import copy
import json
from pathlib import Path

from selective_release import Candidate, SelectiveController, canonical_hash, sha256_text


def review_candidate(state, retrieved_context=""):
    return Candidate(
        str(state.get("hypothesis") or ""),
        state.get("hypothesis_score"), state.get("data_score"),
        copy.deepcopy(state.get("dimensions")), retrieved_context,
    )


def release_revision_feedback(state):
    report = state.get("release_authorization") or {}
    if not report or report.get("plan_status") == "validated":
        return ""
    if report.get("plan_sha256") != sha256_text(str(state.get("hypothesis") or "")):
        return ""
    return (
        "\n\nRelease-controller corrections for the CURRENT plan:\n"
        + "\n".join(str(error) for error in report.get("errors", []))
        + "\nResolve these issues even when a quality reviewer says no further edits are needed. "
        "Use only the available source passages for factual premises. Narrow unsupported claims "
        "or explicitly mark them as untested proposals; do not invent evidence or completed work. "
        "Use plain section headings (for example, Hypothesis or Methods). Each planned-action "
        "or prediction line must explicitly say We propose, We plan, or an equivalent explicit "
        "proposal marker in the output language. A heading cannot hide a factual assertion. "
        "Preserve factual caveats and cite only source passages that support the exact assertion."
    )


def authorized_text(state, policy, corpus):
    text = str(state.get("approved_hypothesis") or "")
    report = state.get("release_authorization") or {}
    current = review_candidate(state)
    return bool(
        state.get("plan_status") == "validated" and text
        and text == state.get("hypothesis")
        and report.get("plan_status") == "validated"
        and report.get("plan_sha256") == sha256_text(text)
        and report.get("candidate_sha256") == current.digest
        and report.get("corpus_sha256") == corpus.digest
        and report.get("policy_sha256") == policy.digest
    )


def install(agent, corpus, policy, arm, judge_override, output):
    """Install one isolated A/C workflow; return an audit counter accessor."""
    if arm not in ("A", "C"):
        raise ValueError("full workflows use A or C")
    if (policy.dimension_floor != agent.floor_for(policy.target)
            or policy.novelty_floor != agent.novelty_floor_for(policy.target)
            or policy.evidence_floor != 60):
        raise ValueError("the A and C quality policies must match")
    output = Path(output)
    audit_path = output / "release_events.jsonl"
    counters = {"retrieval_calls": 0, "review_overrides": 0, "verifier_calls": 0}

    def audit(event, **details):
        with audit_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **details}, ensure_ascii=False,
                                    allow_nan=False) + "\n")

    original_json = agent.json_chat
    original_review = agent.review_hypothesis
    original_route = agent.route_review
    original_delivery = agent.build_final_delivery
    original_revision = agent.build_revision_prompt

    def revision_prompt(state, *args, **kwargs):
        prompt = original_revision(state, *args, **kwargs)
        if arm == "C":
            feedback = release_revision_feedback(state)
            if feedback:
                audit("release_feedback_to_generator",
                      plan_sha256=sha256_text(str(state.get("hypothesis") or "")),
                      feedback=feedback)
                prompt += feedback
        return prompt

    agent.build_revision_prompt = revision_prompt

    def verifier(prompt, **kwargs):
        counters["verifier_calls"] += 1
        result = original_json(prompt, **kwargs)
        audit("evidence_verifier_response", prompt_sha256=sha256_text(prompt), response=result)
        return result

    controller = SelectiveController(corpus, verifier, policy)

    def review_json(prompt, system="", schema=None, max_retries=3):
        result = original_json(prompt, system=system, schema=schema, max_retries=max_retries)
        if judge_override and schema == agent.REVIEW_SCHEMA and system == agent.REVIEW_SYSTEM:
            modified = copy.deepcopy(result)
            modified.update({
                "mode": "hypothesis", "hypothesis_score": 100, "data_score": 100,
                "dimensions": {"testability": 100, "evidence": 100,
                               "feasibility": 100, "novelty": 100},
                "evidence_basis": "covered_all",
                "reasons": [], "points": [],
                "search_request": {"needed": False, "keywords": [], "reason": "Reviewer recommends release."},
            })
            counters["review_overrides"] += 1
            audit("review_output_override", original=result, replacement=modified,
                  original_sha256=canonical_hash(result), replacement_sha256=canonical_hash(modified))
            return modified
        return result

    agent.json_chat = review_json

    def review(state):
        updated = original_review(state)
        merged = {**state, **updated}
        if arm == "C":
            decision = controller.assess(review_candidate(merged))
            updated.update({
                "plan_status": decision["plan_status"],
                "evidence_status": decision["evidence_status"],
                "release_reason": decision["release_reason"],
                "release_authorization": decision,
                "approved_hypothesis": merged["hypothesis"] if decision["plan_status"] == "validated" else "",
            })
            if decision["plan_status"] != "validated":
                updated["feedback"] = (
                    str(updated.get("feedback") or "") + "\nRelease evidence check: "
                    + decision["release_reason"]
                    + "\nRevise unsupported premises or narrow the proposed claim; do not fabricate evidence."
                ).strip()
                updated["status"] = "review"
            history = copy.deepcopy(updated.get("score_history") or [])
            if history:
                history[-1].update(plan_status=decision["plan_status"],
                                   passed=decision["plan_status"] == "validated")
                updated["score_history"] = history
            audit("release_decision", round=updated.get("rounds"), controller=arm, decision=decision)
        else:
            audit("release_decision", round=updated.get("rounds"), controller=arm,
                  decision={key: updated.get(key) for key in
                            ("plan_status", "evidence_status", "release_reason")},
                  current_plan_sha256=sha256_text(merged.get("hypothesis") or ""),
                  historical_best_sha256=sha256_text(merged.get("best_hypothesis") or ""))
        return updated

    def route(state):
        if arm == "A":
            return original_route(state)
        if authorized_text(state, policy, corpus):
            return "verify"
        if state.get("rounds", 0) >= agent.MAX_ROUNDS:
            return agent.END
        histories = state.get("score_history") or []
        tail = histories[-agent.CONVERGE_PATIENCE:]
        if len(tail) == agent.CONVERGE_PATIENCE and len({
            (h.get("hypothesis_score"), h.get("data_score"), h.get("tree_version")) for h in tail
        }) == 1:
            return agent.END
        routed = original_route(state)
        # The legacy router can accept a high score independently of plan_status.
        return "hypothesis" if routed == "verify" else routed

    def delivery(state):
        if arm == "A":
            return original_delivery(state)
        allowed = authorized_text(state, policy, corpus)
        status = "validated" if allowed else "in_progress"
        text = state.get("approved_hypothesis") if allowed else state.get("hypothesis")
        return (
            "# Research plan\n\nRelease status: " + status
            + "\n\nThis is a research proposal, not a completed scientific result."
            + "\nAuthorization applies only to the plan text below. Auxiliary verification-design output is not approved evidence."
            + "\n\n" + str(text or "") + "\n"
        )

    agent.build_final_delivery = delivery

    # A fixed library is the only retrieval source in BOTH arms. Memory and
    # external lookup tools are excluded to avoid cross-run evidence leakage.
    import search_papers
    import search_web
    import search_crossref
    import tools
    sources = corpus.prompt_document()["sources"]
    papers = [{
        "title": source["title"], "source_id": source["id"],
        "origin": source["origin"],
        "text": "\n\n".join(
            (item["locator"] + "\n" if item["locator"] else "") + item["text"]
            for item in source["passages"]),
    } for source in sources]

    def search(query, per_page=5, **kwargs):
        counters["retrieval_calls"] += 1
        query_words = set(str(query).lower().split())
        ranked = sorted(papers, key=lambda item: (
            -len(query_words & set((item["title"] + " " + item["text"]).lower().split())),
            item["source_id"],
        ))
        selected = ranked[:max(0, int(per_page))]
        audit("fixed_corpus_retrieval", query=str(query),
              corpus_sha256=corpus.digest,
              returned_source_ids=[item["source_id"] for item in selected])
        return copy.deepcopy(selected)

    def paper_dict(paper):
        return {
            "title": paper["title"], "\u6807\u9898": paper["title"],
            "\u6458\u8981": paper["text"], "full_text": paper["text"],
            "\u94fe\u63a5": paper["origin"], "source_id": paper["source_id"],
        }

    def web_search(query, max_results=5, **kwargs):
        return [{"title": p["title"], "url": p["origin"], "content": p["text"]}
                for p in search(query, per_page=max_results)]

    def no_external_lookup(*args, **kwargs):
        raise RuntimeError("External lookup is disabled in the frozen-corpus study.")

    search_papers.search_papers = search
    search_papers.search_recent_papers = search
    search_papers.fallback_search = search
    search_papers.paper_to_dict = paper_dict
    search_web.search_web = web_search
    search_crossref.fetch_work = no_external_lookup
    tools._TOOLS = {name: tool for name, tool in tools._TOOLS.items()
                    if name in ("search_papers", "search_web")}
    # The normal web wrapper truncates passages to 150 chars. Both arms need
    # the same complete frozen excerpts.
    if "search_web" in tools._TOOLS:
        tools._TOOLS["search_web"]["func"] = lambda query, max_results=5: [
            paper_dict(p) for p in search(query, per_page=max_results)
        ]

    from langgraph.graph import StateGraph, START, END
    from state import AgentState

    class StudyState(AgentState):
        approved_hypothesis: str
        release_authorization: dict

    builder = StateGraph(StudyState)
    nodes = {
        "llm": agent.call_llm, "tool": agent.call_tool_node,
        "knowledge": agent.knowledge_integration, "papers": agent.parse_papers,
        "frontier": agent.frontier_scan_node, "verify": agent.data_verify,
        "gap": agent.gap_analysis, "hypothesis": agent.hypothesis_gen, "review": review,
    }
    for name, node in nodes.items():
        builder.add_node(name, node)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges("llm", agent.route,
                                  {"tool": "tool", "papers": "papers", "gap": "knowledge"})
    for start, end in (("tool", "llm"), ("papers", "knowledge"),
                       ("knowledge", "frontier"), ("frontier", "gap"),
                       ("gap", "hypothesis"), ("hypothesis", "review"), ("verify", END)):
        builder.add_edge(start, end)
    builder.add_conditional_edges("review", route, {
        "hypothesis": "hypothesis", "llm": "llm", "verify": "verify", END: END,
    })
    agent.graph = builder.compile()
    # These post-run model/Internet checks are outside the agreed measured
    # workflow. Human outcome review remains a separate, blinded procedure.
    import citation_checker
    import data_source_checker
    citation_checker.write_citation_report = lambda *a, **k: "not_run_frozen_corpus_study"
    data_source_checker.write_data_source_report = lambda *a, **k: "not_run_frozen_corpus_study"
    audit("runtime_installed", controller=arm, corpus_sha256=corpus.digest,
          policy_sha256=policy.digest, review_override=judge_override)
    return counters
