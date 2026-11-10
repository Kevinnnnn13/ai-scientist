# -*- coding: utf-8 -*-
"""Deterministic statistical and numeric consistency checks for research plans."""

import argparse
import json
import os
import re
import sys


SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from reviewer_report import _parse_hypotheses, _clean
except Exception:
    _parse_hypotheses = None


def _norm_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _window_quarters(text):
    matches = list(re.finditer(r"(19|20)(\d{2})Q([1-4])[^\dA-Za-z]{0,6}(19|20)(\d{2})Q([1-4])", text))
    if not matches:
        return None
    m = matches[0]
    sy, sq = int(m.group(1) + m.group(2)), int(m.group(3))
    ey, eq = int(m.group(4) + m.group(5)), int(m.group(6))
    return (ey - sy) * 4 + (eq - sq) + 1


def check_window_periods(hyp_name, text):
    expected = _window_quarters(text)
    if expected is None:
        return []
    found = []
    for m in re.finditer(r"\bT\s*=\s*(\d+)", text):
        declared = int(m.group(1))
        if declared != expected:
            found.append(
                {
                    "criterion": "内部一致性",
                    "type": "statistical_inconsistency",
                    "quote": text[max(0, m.start() - 80): m.end() + 80],
                    "reason": f"季度窗口折算为 {expected} 期，但正文写 T={declared}。",
                    "suggested_fix": "统一时间窗口和期数，并重新核对总观测数。",
                }
            )
    return found


def check_event_counts(hyp_name, text):
    values = re.findall(r"(\d+)\s*起", text)
    unique = []
    for value in values:
        if value not in unique:
            unique.append(value)
    if len(unique) > 1:
        return [
            {
                "criterion": "内部一致性",
                "type": "statistical_inconsistency",
                "quote": "事件数量出现多种口径：" + "、".join(unique),
                "reason": "同一假设内出现多个“起”事件计数，且彼此关系未说明。",
                "suggested_fix": "给出事件清单，区分总事件、子集和纳入分析的事件，并统一口径。",
            }
        ]
    return []


def check_pseudoreplication(hyp_name, text):
    indicators = [
        (r"银行[-—]季度|季度观测|观测单位|观测样本", "使用重复观测作为分析单位"),
        (r"Cox", "使用 Cox 生存模型"),
        (r"\b面板\b", "面板数据"),
    ]
    hits = [reason for pattern, reason in indicators if re.search(pattern, text, re.I)]
    if len(hits) >= 2:
        return [
            {
                "criterion": "内部一致性",
                "type": "statistical_inconsistency",
                "quote": "可能存在重复观测进入统计模型",
                "reason": "；".join(hits) + "。同一主体多个时间点通常不独立。",
                "suggested_fix": "确认统计单位是否独立；若为重复观测，改用主体级生存时间或混合效应模型。",
            }
        ]
    return []


def check_false_precision(hyp_name, text):
    issues = []
    patterns = [
        (r"\d+(?:\.\d+)?%\s*(?:\(?95%\s*CI|CI)", "百分比与置信区间"),
        (r"\d+\.\d+\s*\(\s*95%\s*CI", "小数点数值与置信区间"),
        (r"\d+(?:\.\d+)?\s*[±]\s*\d+(?:\.\d+)?", "带误差范围的精确值"),
        (r"R\s*[²2]\s*[=≈]\s*\d+\.\d+", "精确拟合优度"),
        (r"[=≈]\s*\d+\.\d+\s*(?:\(|，|,)", "精确小数估计"),
    ]
    source_markers = (
        "[文献值]", "[推导值]", "[待标定估计]", "[判定阈值]",
        "文献值", "推导值", "待标定", "判定阈值", "估计值",
        "来源：", "来源:", "外推得到", "理论估算",
    )
    for pattern, label in patterns:
        for m in re.finditer(pattern, text):
            start = max(0, m.start() - 180)
            end = min(len(text), m.end() + 180)
            window = text[start:end]
            if any(marker in window for marker in source_markers):
                continue
            issues.append(
                {
                    "criterion": "已知与猜测",
                    "type": "false_precision",
                    "quote": window,
                    "reason": f"{label}未标注推导来源，精度缺少依据。",
                    "suggested_fix": "标注来源、标注“估计”，或降级为量级范围。",
                }
            )
            break
    # Avoid too many repeated hits for one hypothesis.
    return issues[:3]


def check_threshold_gap(hyp_name, text):
    """Flag support/reject thresholds that leave an undefined decision gap."""
    support_values = {}
    reject_values = {}
    clauses = re.split(r"[。\n；;]+", text)
    number_pattern = re.compile(
        r"(?P<op>≥|>|达到|不低于|≤|<|低于|不足)\s*"
        r"(?P<num>\d+(?:\.\d+)?)\s*"
        r"(?P<unit>个数量级|数量级|g/m²/day|mV|bps|%|％|°|倍)?"
    )

    def metric_key(clause, match):
        prefix = clause[max(0, match.start() - 60):match.start()]
        unit = match.group("unit") or ""
        checks = [
            ("r2", r"R\s*[²2]|拟合优度"),
            ("theta", r"Δθ|倾斜角"),
            ("ratio", r"速率比|加速比|coupled/single-sum"),
            ("wvt", r"WVT|水汽透过率"),
            ("hr", r"HR|风险比"),
            ("event_rate", r"事件发生率|风险事件发生率"),
            ("or", r"\bOR\b|优势比"),
            ("lambda", r"λ|衰减率"),
            ("jaccard", r"Jaccard|重合率"),
        ]
        metric = next((name for name, pattern in checks if re.search(pattern, prefix, re.I)), "")
        if not metric:
            return None
        return metric + "|" + unit.lower()

    for clause in clauses:
        if re.search(r"支持|不推翻|接受假设", clause):
            for match in number_pattern.finditer(clause):
                key = metric_key(clause, match)
                if key:
                    support_values.setdefault(key, []).append(float(match.group("num")))
        if re.search(r"推翻|否定假设|拒绝假设", clause):
            for match in number_pattern.finditer(clause):
                key = metric_key(clause, match)
                if key:
                    reject_values.setdefault(key, []).append(float(match.group("num")))
    for key in sorted(set(support_values) & set(reject_values)):
        support = max(support_values[key])
        reject = min(reject_values[key])
        if support <= reject:
            continue
        metric, unit = key.split("|", 1)
        return [
            {
                "criterion": "内部一致性",
                "type": "statistical_inconsistency",
                "quote": f"{metric} 支持阈值 {support:g}{unit}，推翻阈值 {reject:g}{unit}",
                "reason": "同一指标的支持与推翻阈值之间留有未定义灰区，结果落在区间内时无法判定。",
                "suggested_fix": "消除阈值空档，或明确规定灰区结果的处置方式。",
            }
        ]
    return []


def check_question_alignment(question, text):
    q = str(question or "").lower()
    body = text.lower()
    issues = []

    if re.search(r"predict|forecast|预警|能否.*预测|预测能力", q) and not re.search(
        r"样本外|out-of-sample|训练集|测试集|训练/测试|cross-validation|交叉验证|AUC|ROC|accuracy|准确率|预测性能|holdout|held-out",
        body,
    ):
        issues.append(
            {
                "criterion": "信息完整",
                "type": "question_misalignment",
                "quote": question,
                "reason": "题目要求预测能力，但方案缺少样本外验证、训练测试划分或预测性能指标。",
                "suggested_fix": "增加一个直接检验预测性能的假设或验证环节。",
            }
        )

    if re.search(r"如何.*(?:提升|提高|改善|降低|减少|优化)|how\s+to\s+(?:improve|increase|reduce|optimize)", q):
        missing = []
        if not re.search(r"基线|对照|对照组|baseline|control", body):
            missing.append("基线或对照")
        if not re.search(r"干预|处理组|策略|方案|intervention|treatment", body):
            missing.append("可执行干预")
        if not re.search(r"主要结局|最终指标|效果判据|寿命|t80|效率保持|归一化效率|failure|endpoint|outcome", body):
            missing.append("直接的效果结局指标")
        if missing:
            issues.append(
                {
                    "criterion": "信息完整",
                    "type": "question_misalignment",
                    "quote": question,
                    "reason": "题目要求提升/优化效果，但方案缺少：" + "、".join(missing) + "。",
                    "suggested_fix": "增加至少一个直接检验干预相对基线效果的环节，并写明主要结局指标。",
                }
            )
    return issues


def check_unused_references(state, best_text, gap_text):
    literature = state.get("literature") or []
    haystack = _norm_text(str(best_text or "") + " " + str(gap_text or "")).lower()
    used_titles = set()
    try:
        from citation_checker import build_literature_index, find_citations

        index = build_literature_index(state)
        for paper in find_citations(haystack, index):
            used_titles.add(_norm_text(paper.get("title", "")).lower())
    except Exception:
        index = []
    issues = []
    for paper in literature:
        if not isinstance(paper, dict):
            continue
        title = str(paper.get("标题") or paper.get("title") or "").strip()
        if not title:
            continue
        title_norm = _norm_text(title).lower()
        words = title_norm.split()
        fragments = []
        for size in (4, 6, 8, 10):
            if len(words) >= size:
                fragments.append(" ".join(words[:size]))
        if not fragments:
            fragments = [title_norm]
        matched = title.lower() in used_titles
        if not matched:
            matched = any(fragment in haystack for fragment in fragments)
        if not matched:
            issues.append(
                {
                    "criterion": "事实依据",
                    "type": "unused_reference",
                    "quote": title,
                    "reason": "该文献进入文献池，但未在研究假设或缺口文本中被引用。",
                    "suggested_fix": "删除未使用文献，或在正文中说明其实际用途。",
                }
            )
    return issues


def hypothesis_texts(state):
    best = state.get("best_hypothesis") or state.get("hypothesis") or ""
    if _parse_hypotheses is not None:
        out = []
        for title, sections in _parse_hypotheses(best):
            out.append((title, "\n".join(label + ": " + body for label, body in sections)))
        if out:
            return out
    return [("研究假设", best)]


def run_checks(run_dir):
    path = os.path.join(run_dir, "state.json")
    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)

    question = state.get("question") or ""
    best = state.get("best_hypothesis") or state.get("hypothesis") or ""
    gap = state.get("gap") or ""
    issues = []
    for hyp_name, text in hypothesis_texts(state):
        issues.extend(check_window_periods(hyp_name, text))
        issues.extend(check_event_counts(hyp_name, text))
        issues.extend(check_pseudoreplication(hyp_name, text))
        issues.extend(check_false_precision(hyp_name, text))
        issues.extend(check_threshold_gap(hyp_name, text))
    issues.extend(check_question_alignment(question, best))
    issues.extend(check_unused_references(state, best, ""))
    return issues, state


def render_markdown(issues, state, run_dir):
    by_type = {}
    for issue in issues:
        by_type.setdefault(issue["type"], 0)
        by_type[issue["type"]] += 1
    lines = [
        "# 统计与数字一致性核查报告",
        "",
        f"- 运行目录：{run_dir}",
        f"- 研究问题：{state.get('question', '')}",
        f"- 发现问题：{len(issues)}",
        "",
    ]
    if not issues:
        lines.append("未发现明确问题。")
    for idx, issue in enumerate(issues, 1):
        lines.append(f"## {idx}. {issue['type']}")
        lines.append("")
        lines.append(f"- 检查项：{issue['criterion']}")
        lines.append(f"- 原文位置：{issue['quote']}")
        lines.append(f"- 原因：{issue['reason']}")
        lines.append(f"- 建议：{issue['suggested_fix']}")
        lines.append("")
    lines.append("## 汇总")
    lines.append("")
    for typ, count in sorted(by_type.items()):
        lines.append(f"- {typ}: {count}")
    return "\n".join(lines)


def write_report(run_dir):
    issues, state = run_checks(run_dir)
    md = render_markdown(issues, state, run_dir)
    md_path = os.path.join(run_dir, "统计与数字一致性核查报告.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    json_path = os.path.join(run_dir, "统计与数字一致性核查.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"run_dir": run_dir, "issues": issues}, f, ensure_ascii=False, indent=2)
    return md_path


def main():
    parser = argparse.ArgumentParser(description="Run statistical and numeric consistency checks.")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    print(write_report(args.run_dir))


if __name__ == "__main__":
    main()
