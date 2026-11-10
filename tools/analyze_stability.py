# -*- coding: utf-8 -*-
"""批跑结果自动分析：读 _summary.json，按多维规则汇总稳定性结论。

用法：python tools/analyze_stability.py <批跑日志目录>
输出：<目录>/_analysis.md（人类可读）+ 终端摘要
"""
import io
import json
import os
import re
import sys
import time


def safe_print(s):
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((str(s) + "\n").encode("gbk", "replace"))
        sys.stdout.buffer.flush()


def tail_of(path, n=15):
    try:
        with io.open(path, "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(f.read().splitlines()[-n:])
    except Exception:
        return ""


def scan_errors(log_path):
    """在运行日志里找异常关键字，返回分类错误清单。"""
    try:
        with io.open(log_path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
    except Exception:
        return []
    found = []
    patterns = [
        ("traceback", r"Traceback \(most recent call last\)"),
        ("http429", r"HTTP 429|429 Client Error|rate.?limit|限流"),
        ("timeout", r"timeout|Timeout|超时"),
        ("json_retry", r"JSON 解析失败|重试|retry|schema 校验失败"),
        ("no_state", r"未找到结果|done_no_state|找不到 state"),
        ("guard_block", r"blocked|违规|不安全"),
        ("empty_hypothesis", r"假设为空|hypothesis.*空|未生成假设"),
    ]
    for name, pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            found.append(name)
    return found


def main():
    if len(sys.argv) < 2:
        print("用法：python tools/analyze_stability.py <批跑日志目录>")
        sys.exit(1)
    logdir = sys.argv[1]
    sum_path = os.path.join(logdir, "_summary.json")
    if not os.path.isfile(sum_path):
        print(f"找不到 {sum_path}，批跑可能还没结束。")
        sys.exit(1)
    with io.open(sum_path, "r", encoding="utf-8") as f:
        summary = json.load(f)

    items = summary.get("items", [])
    lines = []
    lines.append(f"# 稳定性批跑分析报告（{summary.get('label','')}）")
    lines.append("")
    lines.append(f"- 题数：{summary.get('total')}  目标档位：{summary.get('quality')}")
    lines.append(f"- 完成：{summary.get('done')}  成功：{summary.get('ok')}  失败：{summary.get('fail')}")
    if summary.get("started") and summary.get("finished"):
        lines.append(f"- 总耗时：{(summary['finished']-summary['started'])/60:.1f} 分钟")
    lines.append("")

    scores = [it["best_score"] for it in items if it.get("best_score") is not None]
    data_scores = [it["best_data_score"] for it in items if it.get("best_data_score") is not None]
    seconds = [it.get("seconds") or 0 for it in items]
    if scores:
        lines.append(f"## 分数概览（n={len(scores)}）")
        lines.append(f"- best_score：均值 {sum(scores)/len(scores):.1f}  最小 {min(scores)}  最大 {max(scores)}")
        lines.append(f"- ≥90：{sum(1 for s in scores if s >= 90)}  80-89：{sum(1 for s in scores if 80 <= s < 90)}  70-79：{sum(1 for s in scores if 70 <= s < 80)}  <70：{sum(1 for s in scores if s < 70)}")
    if data_scores:
        lines.append(f"- data_score：均值 {sum(data_scores)/len(data_scores):.1f}  最小 {min(data_scores)}  最大 {max(data_scores)}  <60：{sum(1 for s in data_scores if s < 60)}")
    if seconds:
        lines.append(f"- 单题耗时：均值 {sum(seconds)/len(seconds):.0f}s  中位 {sorted(seconds)[len(seconds)//2]}s  最长 {max(seconds)}s  最短 {min(seconds)}s")
    lines.append("")

    lines.append("## 逐题明细")
    lines.append("")
    lines.append("| # | 状态 | 总分 | 数据分 | 轮次 | 耗时s | 错误/异常 | 题目 |")
    lines.append("|---|------|------|--------|------|-------|-----------|------|")
    for it in items:
        errs = scan_errors(it.get("log") or "")
        if it.get("error"):
            errs.append("state_error")
        status = "OK" if it.get("ok") else "FAIL"
        err_str = ",".join(sorted(set(errs))) or "-"
        q = str(it.get("question") or "")[:44].replace("|", "/")
        lines.append(f"| {it.get('no')} | {status} | {it.get('best_score')} | {it.get('best_data_score')} | {it.get('rounds')} | {it.get('seconds')} | {err_str} | {q} |")
    lines.append("")

    lines.append("## 问题清单（按严重度）")
    lines.append("")
    problems = []
    for it in items:
        no = it.get("no")
        if not it.get("ok"):
            problems.append(f"- **Q{no} 运行失败**：{str(it.get('error') or '无错误信息')[:200]}")
        if it.get("error") and it.get("ok"):
            problems.append(f"- **Q{no} 结束但 state 含 error**：{str(it.get('error'))[:200]}")
        if it.get("best_score") is not None and it["best_score"] < 70:
            problems.append(f"- **Q{no} 总分过低（{it['best_score']}）**：{str(it.get('question') or '')[:60]}")
        if it.get("best_data_score") is not None and it["best_data_score"] < 60:
            problems.append(f"- **Q{no} 数据分过低（{it['best_data_score']}）**：{str(it.get('question') or '')[:60]}（冷门领域需考虑 60-65 档说明）")
        for e in scan_errors(it.get("log") or ""):
            if e in ("traceback", "no_state", "http429"):
                problems.append(f"- **Q{no} 日志含 {e}**")
    lines.extend(problems or ["- 无显著问题"])
    lines.append("")

    report = "\n".join(lines)
    out = os.path.join(logdir, "_analysis.md")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(report)
    safe_print(report)
    safe_print(f"\n分析报告已写入 {out}")


if __name__ == "__main__":
    main()
