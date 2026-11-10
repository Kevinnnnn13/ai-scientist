# -*- coding: utf-8 -*-
"""125 全量输出文档生成器（方向 A 必交材料）。

用法：
  python src/gen_125_report.py                       # 生成主汇总文档
  python src/gen_125_report.py --split               # 每题独立 md 存到 docs/s125_output/

逻辑：
- 扫 27日/生成日志 全部运行，按题目去重（同题多运行取 best_score 最高、轮次最新者）
- 每题输出：题目 / 状态 / 分数 / 最终假设 / 验证摘要 / 12字段研究计划文件路径
- 生成 docs/125全量输出结果.md（含总览统计）
"""
import os
import re
import sys
import json
import io
import time
import difflib
import unicodedata


ALL_125 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "s125_all.txt")


def norm_q(s):
    """题目归一化：NFKC + 去空白/连字符/破折号，忽略大小写。"""
    return re.sub(r"[\s\u2010-\u2015\u002d]+", "", unicodedata.normalize("NFKC", s or "")).lower()


def load_all_questions():
    with io.open(ALL_125, "r", encoding="utf-8-sig") as f:
        return [ln.strip() for ln in f if ln.strip()]

BASE = r"C:\Users\22011\Desktop\26暑假\27日\生成日志"
DOCS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "docs")


def collect_runs():
    """按题目去重：返回 {question: best_run}
    兼容两种日志布局：按日期子目录（2026-08-09/运行NN_...）或直接放根目录（运行NN_...）。
    """
    best = {}

    def scan_folder(root):
        for name in os.listdir(root):
            if not name.startswith("运行"):
                continue
            sj = os.path.join(root, name, "state.json")
            if not os.path.isfile(sj):
                continue
            try:
                with io.open(sj, "r", encoding="utf-8") as f:
                    st = json.load(f)
            except Exception:
                continue
            q = str(st.get("question", "")).strip()
            if not q or q.startswith("找一篇") or q.startswith("运行"):
                continue
            score = st.get("best_score")
            if not isinstance(score, (int, float)):
                score = 0
            m = re.match(r"运行(\d+)", name)
            rid = int(m.group(1)) if m else 0
            day = os.path.basename(root)
            cur = best.get(norm_q(q))
            if cur is None or score > cur["best"] or (score == cur["best"] and rid > cur["rid"]):
                best[norm_q(q)] = {
                    "question": q, "rid": rid, "run": name, "day": day, "folder": os.path.join(root, name),
                    "best": score, "data": st.get("best_data_score"), "status": st.get("status", ""),
                    "rounds": len(st.get("score_history") or []),
                    "hypothesis": (st.get("best_hypothesis") or st.get("hypothesis") or ""),
                    "verification": st.get("verification") or {},
                }

    # 根目录直接放运行文件夹的情况（如运行146+）
    scan_folder(BASE)
    # 日期子目录
    for day in os.listdir(BASE):
        daydir = os.path.join(BASE, day)
        if not os.path.isdir(daydir):
            continue
        if day.startswith("运行"):
            continue  # 已在根目录扫描中处理
        scan_folder(daydir)
    return list(best.values())


def mark(r):
    b = r["best"]
    if b >= 90:
        return "✅ 达标"
    if b >= 85:
        return "🟡 接近"
    if b == 0:
        return "⚫ 0分（网络失败）"
    return "❌ 低分"


def fmt_hyp(h, n=900):
    h = (h or "").strip().replace("\n", " ")
    return h[:n] + ("…" if len(h) > n else "")


def main():
    split = "--split" in sys.argv
    runs = collect_runs()
    canon = load_all_questions()
    norm_canon = [norm_q(q) for q in canon]

    def canon_index(q):
        nq = norm_q(q)
        if nq in norm_canon:
            return norm_canon.index(nq)
        best_i, best_r = None, 0.0
        for i, c in enumerate(norm_canon):
            r = difflib.SequenceMatcher(None, nq, c).ratio()
            if r > best_r:
                best_r, best_i = r, i
        return best_i if best_r >= 0.85 else None

    runs.sort(key=lambda r: (-r["best"], r["rid"]))
    final, seen, unmatched = [], set(), []
    for r in runs:
        ci = canon_index(r["question"])
        if ci is None:
            unmatched.append(r["question"])
            continue
        if ci in seen:
            continue
        seen.add(ci)
        r["question"] = canon[ci]
        final.append(r)
    if unmatched:
        print("未匹配到 125 源题目的运行（已忽略 %d 条）：" % len(unmatched))
        for u in unmatched:
            print("  -", u)

    ge90 = sum(1 for r in final if r["best"] >= 90)
    near = sum(1 for r in final if 85 <= r["best"] < 90)
    low = sum(1 for r in final if 0 < r["best"] < 85)
    zero = sum(1 for r in final if r["best"] == 0)

    lines = ["# AI Scientist · Science 125 全量输出结果\n",
             f"> 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')} · 按 Science 125 源题目归一化去重后共 {len(final)} 题\n",
             f"**总览**：达标（≥90）**{ge90}** · 接近（85-89）**{near}** · 低分（<85）**{low}** · 0分（网络失败待重跑）**{zero}**\n",
             "| # | 题目 | 假设分 | 数据分 | 轮次 | 状态 |", "| --- | --- | --- | --- | --- | --- |"]
    for i, r in enumerate(final, 1):
        lines.append(f"| {i} | {r['question'][:42]} | {r['best']} | {r['data']} | {r['rounds']} | {mark(r)} |")
    lines.append("")

    for i, r in enumerate(final, 1):
        plan = os.path.join(r["folder"], "04_研究计划.md")
        has_plan = os.path.isfile(plan)
        lines.append(f"\n---\n\n## {i}. {r['question']}\n")
        lines.append(f"- 运行：{r['day']}/{r['run']} · 假设分 **{r['best']}** · 数据分 {r['data']} · 迭代 {r['rounds']} 轮 · {mark(r)}")
        lines.append(f"- 12 字段研究计划：{'已生成（' + plan + '）' if has_plan else '待生成'}")
        lines.append(f"\n**最终假设**：\n\n{fmt_hyp(r['hypothesis'])}\n")
        v = r["verification"] or {}
        if v.get("summary"):
            lines.append(f"\n**可验证性摘要**：{str(v['summary'])[:400]}")
        if split:
            sp = os.path.join(DOCS, "s125_output")
            os.makedirs(sp, exist_ok=True)
            with io.open(os.path.join(sp, f"{i:03d}.md"), "w", encoding="utf-8") as f:
                f.write("\n".join(lines[-8:]) + "\n")

    out = os.path.join(DOCS, "125全量输出结果.md")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"已生成：{out}（{len(final)} 题）")
    print(f"统计：达标 {ge90} · 接近 {near} · 低分 {low} · 0分 {zero}")


if __name__ == "__main__":
    main()
