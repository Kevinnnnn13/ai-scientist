# -*- coding: utf-8 -*-
"""Citation and evidence-attribution checker prototype.

Reads a completed run, extracts factual premise text from each hypothesis,
matches it to the literature pool, verifies bibliographic identity through
Crossref where possible, and asks a strict LLM judge whether the cited title is
sufficiently related to the attributed claim.
"""

import argparse
import difflib
import json
import os
import re
import sys


SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from llm_client import json_chat
except Exception:
    json_chat = None

try:
    from search_crossref import fetch_work, paper_summary
except Exception:
    fetch_work = None
    paper_summary = None

try:
    from reviewer_report import _parse_hypotheses, _clean
except Exception:
    _parse_hypotheses = None


SUPPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "reason"],
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["supports", "contradicts", "unrelated", "insufficient"],
        },
        "reason": {"type": "string"},
    },
}

SUPPORT_SYSTEM = """你是严格的科研引文核查员。只根据论文标题和期刊、年份判断标题本身是否足以支持给定主张。

规则：
- 只能使用标题信息，不得假设正文内容。
- 如果标题明确讨论主张的核心主题，判 supports。
- 如果标题方向与主张相反，判 contradicts。
- 如果标题主题明显不同，判 unrelated。
- 如果标题信息不足以判断，判 insufficient，并说明缺什么信息。

只输出 JSON。"""

ORIGIN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["methods"],
    "properties": {
        "methods": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name", "status", "reason"],
                "properties": {
                    "name": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": [
                            "original_cited",
                            "original_missing",
                            "secondary_only",
                            "not_applicable",
                            "unverified",
                        ],
                    },
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

ORIGIN_SYSTEM = """你是严格的科研方法出处核查员。只依据给定主张和文献池标题判断，不得假设看不到的全文内容。

任务：
1. 找出主张中真正依赖的算法、模型、公式、量表、协议、数据库定义或核心统计方法。
2. 判断这些方法的原始出处是否出现在给定文献池标题中。

状态只能使用：
- original_cited：原始出处已在文献池中出现，且主张中有明确引用。
- secondary_only：只引用了应用/改进/二手论文，未引用原始出处。
- original_missing：方法被使用，但原始出处不在给定文献池中。
- not_applicable：该方法没有明确的单一原始出处，或只是通用软件/常识。
- unverified：仅凭标题无法判断原始出处，不能算通过。

规则：
- 通用软件名（如 Python、Stata、Excel）判 not_applicable。
- 只在文献池中有同名或相似应用论文，不足以判 original_cited。
- 没有把握时判 unverified，不得猜测。
- methods 只列真正影响研究结论的方法；最多 5 条。
只输出 JSON。"""


def _norm_title(value):
    value = str(value or "").lower()
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _journal_key(value):
    value = str(value or "").lower()
    value = re.sub(r"&", " and ", value)
    value = re.sub(r"[^0-9a-z]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


JOURNAL_ALIASES = {
    "pccp": "physical chemistry chemical physics",
    "science": "science",
    "nature": "nature",
    "adv mater": "advanced materials",
    "acs appl mater interfaces": "acs applied materials interfaces",
}


def _journal_matches(citation_text, journal):
    ct = _journal_key(citation_text)
    jt = _journal_key(journal)
    if not ct or not jt:
        return False
    if ct == jt:
        return True
    if ct in jt or jt in ct:
        return True
    if ct in JOURNAL_ALIASES and JOURNAL_ALIASES[ct] in jt:
        return True
    return any(alias == ct and alias in jt for alias in JOURNAL_ALIASES)


def _norm_doi(value):
    value = str(value or "").strip()
    value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", value, flags=re.I)
    return value.lower()


def _title_similarity(a, b):
    a, b = _norm_title(a), _norm_title(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def load_run_state(run_dir):
    path = os.path.join(run_dir, "state.json")
    if not os.path.isfile(path):
        raise FileNotFoundError("missing state.json: " + path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_literature_index(state):
    index = []
    seen = set()
    for paper in state.get("literature") or []:
        if not isinstance(paper, dict):
            continue
        title = str(paper.get("标题") or paper.get("title") or "").strip()
        doi = _norm_doi(paper.get("DOI") or paper.get("doi") or "")
        key = (title, doi)
        if key in seen or not title:
            continue
        seen.add(key)
        index.append(
            {
                "title": title,
                "doi": doi,
                "journal": str(paper.get("期刊") or paper.get("journal") or "").strip(),
                "year": str(paper.get("年份") or paper.get("year") or "").strip(),
            }
        )
    return index


def extract_premises(state):
    if _parse_hypotheses is None:
        return []
    best = state.get("best_hypothesis") or state.get("hypothesis") or ""
    premises = []
    for title, sections in _parse_hypotheses(best):
        full_text = "\n".join(label + "：" + body for label, body in sections)
        for label, body in sections:
            if label in ("背景依据", "提出依据"):
                premises.append(
                    {
                        "hypothesis": title,
                        "label": label,
                        "text": body,
                        "origin_text": full_text,
                    }
                )
    if not premises and state.get("gap"):
        premises.append({"hypothesis": "研究缺口", "label": "背景依据", "text": state.get("gap")})
    return premises


def find_citations(text, literature):
    found = []
    normalized_text = _norm_title(text)
    seen = set()

    def add(paper):
        key = (paper["title"], paper["doi"])
        if key not in seen:
            seen.add(key)
            found.append(paper)

    for paper in literature:
        title_norm = _norm_title(paper["title"])
        if not title_norm:
            continue
        # Match a sufficiently long title fragment or the normalized DOI.
        frag = title_norm[:90]
        if frag in normalized_text:
            add(paper)
            continue
        if len(title_norm) >= 24 and title_norm in normalized_text:
            add(paper)
            continue
        if paper["doi"] and paper["doi"] in text.lower():
            add(paper)

    # Handle short citations such as 《Science, 2017》 or (Nature, 2016).
    tokens = re.findall(r"[《「(（]([^《》「」()（）]{3,160})[》」)）]", text)
    for token in tokens:
        year_match = re.search(r"(19|20)\d{2}", token)
        year = year_match.group(0) if year_match else ""
        for paper in literature:
            if year and paper["year"] and year != paper["year"]:
                continue
            token_norm = _norm_title(token)
            title_norm = _norm_title(paper["title"])
            if len(token_norm) >= 24 and token_norm in title_norm:
                add(paper)
                continue
            if year and _journal_matches(re.sub(r"(19|20)\d{2}", "", token), paper["journal"]):
                add(paper)
    return found


def verify_identity(paper):
    if fetch_work is None or not paper["doi"]:
        return {"checked": False, "status": "skip", "note": "无 DOI 或无法访问 CrossRef"}
    try:
        summary = paper_summary(fetch_work(paper["doi"]))
    except Exception as exc:
        return {"checked": False, "status": "unresolved", "note": str(exc)[:120]}

    remote_title = str(summary.get("标题") or "").strip()
    remote_year = str(summary.get("年份") or "").strip()
    sim = _title_similarity(paper["title"], remote_title)
    issues = []
    if remote_title and sim < 0.72:
        issues.append(f"标题相似度低({sim:.2f})")
    if paper["year"] and remote_year and paper["year"] != remote_year:
        issues.append(f"年份不一致(本地 {paper['year']}, CrossRef {remote_year})")
    status = "ok" if not issues else "mismatch"
    return {
        "checked": True,
        "status": status,
        "note": "；".join(issues) if issues else "CrossRef 身份核对通过",
        "remote_title": remote_title,
        "remote_year": remote_year,
    }


def judge_support(premise, paper):
    if json_chat is None:
        return {"verdict": "insufficient", "reason": "LLM 不可用"}
    prompt = (
        "主张：\n"
        + str(premise)[:1800]
        + "\n\n论文标题："
        + paper["title"]
        + "\n期刊："
        + paper["journal"]
        + "\n年份："
        + paper["year"]
    )
    try:
        return json_chat(prompt, system=SUPPORT_SYSTEM, schema=SUPPORT_SCHEMA, max_retries=1)
    except Exception as exc:
        return {"verdict": "insufficient", "reason": str(exc)[:120]}


def judge_original_sources(premise, literature):
    """Check whether central methods cite their original sources in the pool."""
    text = str(premise or "")
    if not re.search(
        r"算法|模型|公式|量表|协议|数据库|指数|框架|估计量|统计方法|"
        r"algorithm|model|equation|protocol|database|index|framework|estimator",
        text,
        re.I,
    ):
        return []
    if json_chat is None:
        return [
            {
                "name": "方法原始出处",
                "status": "unverified",
                "reason": "LLM 不可用，无法核查原始方法出处。",
            }
        ]
    titles = "\n".join(f"- {paper['title']}" for paper in literature[:30])
    prompt = (
        "研究主张：\n"
        + text[:2200]
        + "\n\n给定文献池标题：\n"
        + (titles or "（空）")
    )
    try:
        data = json_chat(prompt, system=ORIGIN_SYSTEM, schema=ORIGIN_SCHEMA, max_retries=1)
    except Exception as exc:
        return [
            {
                "name": "方法原始出处",
                "status": "unverified",
                "reason": str(exc)[:160],
            }
        ]
    methods = data.get("methods") if isinstance(data, dict) else []
    out = []
    for item in methods or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        status = str(item.get("status") or "unverified").strip()
        reason = str(item.get("reason") or "").strip()
        if name and status:
            out.append({"name": name, "status": status, "reason": reason})
    return out[:5]


def run_checks(run_dir, use_llm=True, verify_doi=True):
    state = load_run_state(run_dir)
    literature = build_literature_index(state)
    records = []
    for premise in extract_premises(state):
        text = premise["text"]
        cited = find_citations(text, literature)
        origin_checks = (
            judge_original_sources(premise.get("origin_text") or text, literature)
            if use_llm else []
        )
        origin_problems = [
            item for item in origin_checks
            if item.get("status") in ("original_missing", "secondary_only", "unverified")
        ]
        if not cited:
            issues = []
            for item in origin_problems:
                issues.append(
                    f"原始方法出处未核实（{item.get('name', '')}，{item.get('status', '')}）："
                    + item.get("reason", "")
                )
            records.append(
                {
                    "premise": text[:600],
                    "hypothesis": premise["hypothesis"],
                    "paper": {"title": "原始方法出处核查"} if issues else None,
                    "issue": "original_source_attribution" if issues else "no_citation_found",
                    "severity": "fail" if any(
                        item.get("status") in ("original_missing", "secondary_only")
                        for item in origin_problems
                    ) else ("review" if issues else "warning"),
                    "detail": (
                        "未能把该段背景依据匹配到文献池中的具体条目。"
                        if not issues else "引用池中没有可匹配条目，且原始方法出处存在风险。"
                    ),
                    "identity": {},
                    "support": {},
                    "issues": issues or ["未能把该段背景依据匹配到文献池中的具体条目。"],
                }
            )
            continue
        for paper in cited:
            identity = verify_identity(paper) if verify_doi else {"checked": False, "status": "skip", "note": "跳过 DOI 核验"}
            support = judge_support(text, paper) if use_llm else {"verdict": "insufficient", "reason": "跳过 LLM 判断"}
            issues = []
            if identity.get("status") in ("mismatch", "unresolved"):
                issues.append("身份核验未通过: " + identity.get("note", ""))
            if support.get("verdict") in ("unrelated", "contradicts"):
                issues.append("主题不匹配: " + support.get("reason", ""))
            elif support.get("verdict") == "insufficient":
                issues.append("标题信息不足: " + support.get("reason", ""))
            if paper is cited[0]:
                for item in origin_problems:
                    issues.append(
                        f"原始方法出处未核实（{item.get('name', '')}，{item.get('status', '')}）："
                        + item.get("reason", "")
                    )

            quoted = bool(re.search(r"[\u201c\u201d\"'].{12,}[\u201c\u201d\"']", text))
            if quoted:
                issues.append("含引文但无页码或段落定位")

            severity = "fail" if any(x.startswith(("身份核验未通过", "主题不匹配")) for x in issues) else (
                "review" if issues else "pass"
            )
            if paper is cited[0] and any(
                item.get("status") in ("original_missing", "secondary_only")
                for item in origin_problems
            ):
                severity = "fail"
            records.append(
                {
                    "premise": text[:600],
                    "hypothesis": premise["hypothesis"],
                    "paper": paper,
                    "identity": identity,
                    "support": support,
                    "issues": issues,
                    "severity": severity,
                }
            )
    return records, state


def render_markdown(records, state, run_dir):
    lines = [
        "# 引用归属核查报告",
        "",
        f"- 运行目录：{run_dir}",
        f"- 研究问题：{state.get('question', '')}",
        f"- 文献池条目：{len(state.get('literature') or [])}",
        "",
    ]
    severity_count = {"pass": 0, "review": 0, "fail": 0, "warning": 0}
    for record in records:
        severity_count[record.get("severity", "review")] += 1
    lines.append(
        f"- 结果：通过 {severity_count['pass']}，需复核 {severity_count['review']}，"
        f"失败 {severity_count['fail']}，警告 {severity_count['warning']}"
    )
    lines.append("")

    for idx, record in enumerate(records, 1):
        paper = record.get("paper") or {}
        title = paper.get("title", "未匹配到文献")
        lines.append(f"## {idx}. {title}")
        lines.append("")
        lines.append(f"- 假设位置：{record.get('hypothesis', '')}")
        lines.append(f"- 判定：{record.get('severity', '')}")
        lines.append("")
        lines.append("**背景依据片段**")
        lines.append("")
        lines.append(record.get("premise", ""))
        lines.append("")
        if paper:
            lines.append(
                f"- 本地元数据：{paper.get('journal', '')}，{paper.get('year', '')}，DOI `{paper.get('doi', '')}`"
            )
            lines.append("")
        identity = record.get("identity") or {}
        support = record.get("support") or {}
        lines.append("**核查结果**")
        lines.append("")
        if identity.get("note"):
            lines.append(f"- 身份：{identity.get('note', '')}")
        lines.append(f"- 标题支持判断：{support.get('verdict', '')}：{support.get('reason', '')}")
        for issue in record.get("issues") or []:
            lines.append(f"- 问题：{issue}")
        if not (record.get("issues") or []):
            lines.append("- 未发现明确问题。")
        lines.append("")

    lines.append("## 说明")
    lines.append("")
    lines.append("本原型只使用论文标题进行支持方向判断，不读取全文；insufficient 表示仅凭标题无法确认，不代表一定错误。")
    return "\n".join(lines)


def write_citation_report(run_dir, use_llm=True, verify_doi=True):
    """Run checks and write 引用归属核查报告.md into the run directory."""
    records, state = run_checks(run_dir, use_llm=use_llm, verify_doi=verify_doi)
    md = render_markdown(records, state, run_dir)
    out_path = os.path.join(run_dir, "引用归属核查报告.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Run citation attribution checks on a completed AI Scientist run.")
    parser.add_argument("run_dir")
    parser.add_argument("--no-llm", action="store_true", help="Disable LLM support-direction judge")
    parser.add_argument("--no-doi", action="store_true", help="Disable Crossref DOI verification")
    parser.add_argument("--out", default="", help="Output Markdown path")
    args = parser.parse_args()

    if args.out or args.no_llm or args.no_doi:
        records, state = run_checks(
            args.run_dir,
            use_llm=not args.no_llm,
            verify_doi=not args.no_doi,
        )
        md = render_markdown(records, state, args.run_dir)
        out_path = args.out or os.path.join(args.run_dir, "引用归属核查报告.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
    else:
        out_path = write_citation_report(args.run_dir)
    print(out_path)


if __name__ == "__main__":
    main()
