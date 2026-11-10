# -*- coding: utf-8 -*-
"""前沿风向扫描模块（2026-08-29 新增）。

功能：给定科学问题，检索「最近 N 年」该领域约 10 篇论文，由 LLM 总结最新研究风向
（热点主题 / 方法趋势 / 争议与开放问题 / 代表性新工作）。

设计原则：
- 独立旁路模块：不改主检索链路、不进文献池、不碰评审评分；
- 失败自动跳过（fail-open）：搜索全失败 / LLM 异常都不会让主流程崩；
- 输出：结构化 report（dict）+ 可读 text（markdown），由上层落盘与前端展示。

用法（独立测试）：
  python src/frontier_scan.py "钙钛矿太阳能电池稳定性" --years 3
"""
import json
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
import search_papers
import llm_client

DEFAULT_YEARS = 3
TARGET_PAPERS = 10          # 目标论文数（约）
MAX_KEYWORDS = 3            # 最多提炼几个领域搜索词
PER_KEYWORD = 8             # 每个搜索词最多取几篇（2026-08-30：5→8，补偿预印本过滤后的论文数量）

# 低质量文献标记（预印本/杂物平台，非同行评议期刊）：命中即排除
LOW_QUALITY_MARKERS = ("ssrn", "preprints", "zenodo", "10.5281", "10.20944",
                       "10.2139", "10.21203", "researchsquare", "researchgate",
                       "figshare", "osf.io", "10.14293", "10.22541", "authorea",
                       "10.35534", "10.61173")

KEYWORDS_SCHEMA = {
    "type": "object",
    "properties": {
        "keywords": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-3 个该领域前沿文献检索用英文关键词，具体、可检索、避免过宽泛",
        }
    },
    "required": ["keywords"],
}

SUMMARY_SYSTEM = """你是一个科学前沿分析助手。基于给定的「最近几年论文列表」，总结该领域最新研究风向。
要求：
1. 只基于给定的论文，不得脑补列表之外的文献；
2. 输出四部分：hotspots（热点主题 2-4 个，每个一句话）、method_trends（方法/技术趋势 1-2 句）、
   debates（争议或开放问题，论文中有才写，没有就输出空数组 []）、representative（代表性新工作 2-4 条，
   每条**必须是一段纯字符串**，格式：标题（年份）— 为什么重要，禁止嵌套对象）；
3. 若论文不足 5 篇，在 summary 中明确说明「该领域近期文献较少，风向判断置信度有限」；
4. 语言与用户问题一致（中文问题输出中文，英文问题输出英文）。"""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string", "description": "一段总体风向总结（100-200 字）"},
        "hotspots": {"type": "array", "items": {"type": "string"}},
        "method_trends": {"type": "string"},
        "debates": {"type": "array", "items": {"type": "string"}, "allowEmpty": True,
                    "description": "争议或开放问题；没有则输出空数组"},
        "representative": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["summary", "hotspots", "method_trends", "debates", "representative"],
}


def _extract_keywords(question, max_keywords=MAX_KEYWORDS, is_zh=False):
    """LLM 从问题提炼领域检索关键词（失败返回空列表）。"""
    lang_req = ("（原始问题为中文：每个关键词写成「英文关键词 | 中文关键词」双语形式，"
                "用 | 分隔；英文用于国际文献检索，中文用于中文文献池检索。）"
                if is_zh else "")
    try:
        obj = llm_client.json_chat(
            f"请为下面这个科学问题提炼 2-3 个「该领域前沿文献检索」用的英文关键词"
            f"（具体、可检索、避免过宽泛）{lang_req}：\n\n{question}",
            system="你是科学文献检索专家，只输出结构化关键词。",
            schema=KEYWORDS_SCHEMA,
            max_retries=2,
        )
        return [str(k).strip() for k in (obj.get("keywords") or []) if str(k).strip()][:max_keywords]
    except Exception:
        return []


def _collect_papers(keywords, years, target=TARGET_PAPERS, per_keyword=PER_KEYWORD):
    """按关键词检索最近 N 年文献，去重合并到 target 篇左右（失败源自动跳过）。"""
    seen = set()
    papers = []
    for kw in keywords:
        kw_en = kw.split(" | ")[0].strip()
        kw_zh = kw.split(" | ")[1].strip() if " | " in kw else ""
        try:
            raw = search_papers.search_recent_papers(kw_en, per_page=per_keyword, years=years)
            if kw_zh:
                try:
                    raw += search_papers.search_recent_papers(kw_zh, per_page=min(3, per_keyword // 2), years=years)
                except Exception:
                    pass
        except Exception:
            raw = []
        for p in raw:
            try:
                d = search_papers.paper_to_dict(p)
            except Exception:
                continue
            title = str(d.get("标题") or "").strip()
            if not title or title in seen:
                continue
            # 低质量过滤：预印本/杂物平台（SSRN/preprints/Zenodo 等）不进风向总结
            doi = str(d.get("DOI") or "").lower()
            if any(m in doi for m in LOW_QUALITY_MARKERS):
                continue
            seen.add(title)
            papers.append(d)
            if len(papers) >= target:
                return papers
    return papers


def _render_markdown(question, years, papers, report):
    """把结果渲染成 markdown 文本。"""
    lines = [f"# 前沿风向（最近 {years} 年）", ""]
    lines.append(f"**领域**：{question}")
    lines.append("")
    lines.append(f"**总体风向**：{report.get('summary', '')}")
    lines.append("")
    hotspots = report.get("hotspots") or []
    if hotspots:
        lines.append("**热点主题**：")
        lines += [f"- {h}" for h in hotspots]
        lines.append("")
    lines.append(f"**方法趋势**：{report.get('method_trends', '')}")
    lines.append("")
    debates = report.get("debates") or []
    if debates:
        lines.append("**争议 / 开放问题**：")
        lines += [f"- {d}" for d in debates]
        lines.append("")
    rep = report.get("representative") or []
    if rep:
        lines.append("**代表性新工作**：")
        lines += [f"- {r}" for r in rep]
        lines.append("")
    lines.append(f"**检索到的论文（{len(papers)} 篇）**：")
    for p in papers[:TARGET_PAPERS + 2]:
        lines.append(f"- [{p.get('年份') or '?'}]《{p.get('标题')}》（{p.get('期刊') or ''}）{p.get('DOI') or ''}")
    if len(papers) < 5:
        lines.append("")
        lines.append("> 注：该领域近期文献较少，风向判断置信度有限。")
    return "\n".join(lines)


def scan_frontier(question, years=DEFAULT_YEARS):
    """执行前沿扫描。返回 dict：
      {ready, years, keywords, papers, report, text, error, ts}
    ready=False 表示不可用（检索空/异常），主流程应跳过展示。
    """
    result = {"ready": False, "years": years, "keywords": [], "papers": [],
              "report": None, "text": "", "error": None,
              "ts": time.strftime("%Y-%m-%d %H:%M:%S")}
    question = (question or "").strip()
    if not question:
        result["error"] = "问题为空，无法扫描"
        return result
    try:
        # 1) 提炼领域搜索词
        import re as _re
        is_zh = bool(_re.search(r"[\u4e00-\u9fff]", question))
        keywords = _extract_keywords(question, is_zh=is_zh)
        result["keywords"] = keywords
        if not keywords:
            result["error"] = "关键词提炼失败"
            return result
        # 2) 检索最近 N 年论文
        papers = _collect_papers(keywords, years)
        result["papers"] = papers
        if not papers:
            result["error"] = f"最近 {years} 年未检索到相关文献（领域冷门或检索服务不可用）"
            return result
        # 3) LLM 总结风向
        paper_text = "\n".join(
            f"- [{p.get('年份') or '?'}]《{p.get('标题')}》（{p.get('期刊') or ''}）"
            for p in papers[:TARGET_PAPERS + 2]
        )
        prompt = (f"以下是「{question}」领域最近 {years} 年的 {len(papers)} 篇论文：\n\n"
                  f"{paper_text}\n\n请总结该领域最新研究风向。")
        report = llm_client.json_chat(prompt, system=SUMMARY_SYSTEM,
                                      schema=SUMMARY_SCHEMA, max_retries=2)
        result["report"] = report
        result["text"] = _render_markdown(question, years, papers, report)
        result["ready"] = True
    except Exception as e:
        result["error"] = f"前沿扫描异常：{str(e)[:300]}"
    return result


def main():
    def _safe_print(s):
        try:
            print(s, flush=True)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((str(s) + "\n").encode("gbk", "replace"))
            sys.stdout.buffer.flush()

    years = DEFAULT_YEARS
    args = sys.argv[1:]
    if "--years" in args:
        i = args.index("--years")
        years = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    question = " ".join(args).strip() or "钙钛矿太阳能电池长期稳定性如何提升？"
    r = scan_frontier(question, years=years)
    _safe_print(json.dumps({k: r[k] for k in ("ready", "years", "keywords", "papers", "error")},
                           ensure_ascii=False, indent=2))
    _safe_print("\n" + r["text"])


if __name__ == "__main__":
    main()
