# -*- coding: utf-8 -*-
"""离线单测：前沿风向扫描模块（mock 检索 + mock LLM，不联网）。"""
import sys
import os
from unittest import mock

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, SRC)
import frontier_scan

passed = 0
failed = 0


def check(name, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  [PASS] {name}")
    else:
        failed += 1
        print(f"  [FAIL] {name} {detail}")


FAKE_PAPERS = [
    {"title": "Perovskite solar cells beyond 26% efficiency: latest advances", "publication_year": 2026,
     "authorships": [], "primary_location": {"source": {"display_name": "Nature Energy"}},
     "cited_by_count": 120, "doi": "10.1038/s41560-026-00001-1"},
    {"title": "Ion migration and phase segregation in metal halide perovskites", "publication_year": 2025,
     "authorships": [], "primary_location": {"source": {"display_name": "Joule"}},
     "cited_by_count": 88, "doi": "10.1016/j.joule.2025.01.001"},
    {"title": "Accelerated aging protocols for perovskite module stability", "publication_year": 2025,
     "authorships": [], "primary_location": {"source": {"display_name": "ACS Energy Letters"}},
     "cited_by_count": 45, "doi": "10.1021/acsenergylett.5c00001"},
    {"title": "Machine learning guided composition optimization of perovskites", "publication_year": 2024,
     "authorships": [], "primary_location": {"source": {"display_name": "Advanced Materials"}},
     "cited_by_count": 200, "doi": "10.1002/adma.202400001"},
    {"title": "Encapsulation strategies against moisture degradation", "publication_year": 2026,
     "authorships": [], "primary_location": {"source": {"display_name": "Science"}},
     "cited_by_count": 10, "doi": "10.1126/science.adm0001"},
]

FAKE_REPORT = {
    "summary": "钙钛矿领域近年聚焦于效率突破与稳定性耦合、离子迁移-相分离机制，以及加速老化与AI辅助优化。",
    "hotspots": ["效率-稳定性协同优化", "离子迁移与相分离机制", "加速老化协议标准化"],
    "method_trends": "从单一实验向原位表征+机器学习闭环演进",
    "debates": ["离子迁移是否主导长期降解"],
    "representative": ["Perovskite solar cells beyond 26%（2026）— 效率新纪录", "Accelerated aging protocols（2025）— 测试标准化"],
}


def fake_json_chat(prompt, system="", schema=None, max_retries=3):
    if "提炼" in prompt or "英文关键词" in prompt:
        return {"keywords": ["perovskite solar cells stability", "ion migration phase segregation"]}
    return FAKE_REPORT


# ---- 1) 全流程成功 ----
with mock.patch("frontier_scan.search_papers.search_recent_papers",
                return_value=FAKE_PAPERS), \
     mock.patch("frontier_scan.llm_client.json_chat", side_effect=fake_json_chat):
    print("== 1) scan_frontier 全流程 ==")
    r = frontier_scan.scan_frontier("钙钛矿太阳能电池长期稳定性如何提升？", years=3)
    check("ready=True", r["ready"] is True, str(r.get("error")))
    check("关键词 2 个", len(r["keywords"]) == 2, str(r["keywords"]))
    check("论文去重 5 篇", len(r["papers"]) == 5, str(len(r["papers"])))
    check("report 有 summary", bool(r["report"] and r["report"].get("summary")))
    check("markdown 含总体风向", "总体风向" in r["text"])
    check("markdown 含论文列表", "检索到的论文（5 篇）" in r["text"])
    check("markdown 含年份", "[2026]" in r["text"])

# ---- 2) 检索为空 -> ready=False，不崩 ----
with mock.patch("frontier_scan.search_papers.search_recent_papers", return_value=[]), \
     mock.patch("frontier_scan.llm_client.json_chat", side_effect=fake_json_chat):
    print("== 2) 检索为空容错 ==")
    r = frontier_scan.scan_frontier("超冷门领域问题", years=1)
    check("ready=False", r["ready"] is False)
    check("有错误说明", bool(r.get("error")))
    check("text 为空不崩", r["text"] == "")

# ---- 3) 关键词提炼失败 -> ready=False ----
with mock.patch("frontier_scan.search_papers.search_recent_papers",
                return_value=FAKE_PAPERS), \
     mock.patch("frontier_scan.llm_client.json_chat",
                side_effect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("mock LLM 失败"))):
    print("== 3) LLM 异常容错 ==")
    r = frontier_scan.scan_frontier("任何问题", years=3)
    check("ready=False", r["ready"] is False)
    check("有错误说明", bool(r.get("error")))

# ---- 4) 年份窗口参数传递 ----
with mock.patch("frontier_scan.search_papers.search_recent_papers",
                return_value=FAKE_PAPERS) as m_rep, \
     mock.patch("frontier_scan.llm_client.json_chat", side_effect=fake_json_chat):
    frontier_scan.scan_frontier("问题", years=1)
    kw = m_rep.call_args
    check("years=1 传给检索函数", kw.kwargs.get("years") == 1, str(kw))

# ---- 5) 低质量文献过滤（SSRN/preprints/Zenodo 不进总结）----
FAKE_WITH_JUNK = FAKE_PAPERS + [
    {"title": "An unreviewed preprint on perovskite", "publication_year": 2025,
     "authorships": [], "primary_location": {"source": {"display_name": ""}},
     "cited_by_count": 0, "doi": "10.2139/ssrn.9999999"},
    {"title": "Zenodo random upload", "publication_year": 2026,
     "authorships": [], "primary_location": {"source": {"display_name": ""}},
     "cited_by_count": 0, "doi": "10.5281/zenodo.123456"},
]

with mock.patch("frontier_scan.search_papers.search_recent_papers", return_value=FAKE_WITH_JUNK), \
     mock.patch("frontier_scan.llm_client.json_chat", side_effect=fake_json_chat):
    print("== 5) 低质量文献过滤 ==")
    r = frontier_scan.scan_frontier("钙钛矿稳定性", years=3)
    check("预印本被过滤", all("ssrn" not in str(p.get("DOI")) for p in r["papers"]))
    check("Zenodo 被过滤", all("zenodo" not in str(p.get("DOI")) for p in r["papers"]))
    check("保留正常文献 5 篇", len(r["papers"]) == 5, f"got {len(r['papers'])}")

print(f"\n== 前沿扫描离线单测：{passed} PASS / {failed} FAIL ==")
sys.exit(1 if failed else 0)
