# -*- coding: utf-8 -*-
"""Deterministic checks for unverifiable figure, table and experiment anchors."""

import argparse
import json
import os
import re
import sys


SPECIFIC_LOCATOR_RE = re.compile(
    r"(?:(?:文献|reference|ref\.?)\s*(?:\[\s*\d+\s*\]|\d+)\s*)?"
    r"(?:(?:图|表)\s*[A-Za-z]?\d+[A-Za-z]?|"
    r"\bFig(?:ure)?\.?\s*[A-Za-z]?\d+[A-Za-z]?|"
    r"\bTable\s*[A-Za-z]?\d+[A-Za-z]?|"
    r"(?:Supporting|Supplementary)\s+(?:Information|Fig(?:ure)?\.?|Table)|"
    r"补充材料|补充信息|"
    r"(?<![A-Za-z0-9_])(?-i:SI)\s*(?:Fig(?:ure)?\.?|Table|Appendix|Section)|"
    r"(?:见|参见|详见|see)\s*(?:the\s+)?(?-i:SI)\b)",
    re.I,
)

PREEXPERIMENT_RE = re.compile(
    r"(?:预|初步|先导|前期)(?:实验|试验|测试|研究|数据)"
    r"[^。！？!?；;\n]{0,100}"
    r"(?:证实|表明|显示|证明|发现|测得|获得|完成|观察到|已开展|结果是)",
    re.I,
)

COMPLETED_EXPERIMENT_RE = re.compile(
    r"(?:已|已经|目前)(?:完成|开展|做)?(?:了)?"
    r"(?:预|初步|先导)?(?:实验|试验|测试)"
    r"[^。！？!?；;\n]{0,80}"
    r"(?:证实|表明|显示|证明|发现|测得|获得|观察到|结果)",
    re.I,
)

SELF_RESULT_RE = re.compile(
    r"(?:我们|本研究|本课题组|课题组|本团队)"
    r"[^。！？!?；;\n]{0,60}"
    r"(?:已|已经)?"
    r"(?:测得|完成|观察到|发现|证实|证明)"
    r"[^。！？!?；;\n]{0,80}",
    re.I,
)

FUTURE_MARKERS = (
    "计划", "拟", "将", "拟开展", "待开展", "预计", "尚未", "尚未开展",
    "若", "如果", "一旦",
)


def _text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _sentences(text):
    text = str(text or "")
    parts = re.split(r"(?<=[。！？!?；;\n])", text)
    return [p.strip() for p in parts if p.strip()]


def _short(text, limit=260):
    value = _text(text)
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "……"


def _has_full_text_source(state):
    for key in ("literature", "given_papers", "paper_cards"):
        items = state.get(key) if isinstance(state, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            for field in ("全文", "full_text", "fulltext", "正文", "paper_text", "content", "text"):
                value = item.get(field)
                if isinstance(value, str) and len(value.strip()) >= 500:
                    return True
    return False


def check_hypothesis(text, state=None):
    """Return deterministic anchor issues found in hypothesis text.

    The checker does not claim that a cited figure is false. It flags a
    specific locator or an experiment-result claim when the run has no
    verifiable full text or recorded experiment output for it.
    """
    state = state if isinstance(state, dict) else {}
    full_text_available = _has_full_text_source(state)
    issues = []
    seen = set()

    for sentence in _sentences(text):
        locator_matches = list(SPECIFIC_LOCATOR_RE.finditer(sentence))
        if locator_matches:
            locators = sorted({m.group(0).strip() for m in locator_matches})
            key = ("specific_locator", _text(sentence))
            if key not in seen:
                seen.add(key)
                issues.append(
                    {
                        "type": "specific_locator",
                        "severity": "hard",
                        "quote": _short(sentence),
                        "reason": "正文引用了具体图表、页码或补充材料定位，但当前运行没有可核验的全文/附件记录。",
                        "suggested_fix": "删除具体图号/补充材料定位，或改成标题级、待核验表述；确需保留时必须提供可定位的原文。",
                        "locators": locators,
                        "full_text_available": full_text_available,
                    }
                )

    experiment_patterns = [
        ("unverified_experiment_claim", PREEXPERIMENT_RE),
        ("unverified_experiment_claim", COMPLETED_EXPERIMENT_RE),
        ("unverified_self_result", SELF_RESULT_RE),
    ]
    for sentence in _sentences(text):
        # 未来计划本身不是既成事实；只有明确声称已完成、已观察或已测得
        # 才由本检查器拦截。具体图表定位仍单独检查。
        if any(marker in sentence for marker in FUTURE_MARKERS):
            continue
        for issue_type, pattern in experiment_patterns:
            match = pattern.search(sentence)
            if not match:
                continue
            key = (issue_type, _text(sentence))
            if key in seen:
                continue
            seen.add(key)
            issues.append(
                {
                    "type": issue_type,
                    "severity": "hard",
                    "quote": _short(sentence),
                    "reason": "正文把尚未记录在本运行中的实验、测量或课题组结果写成了既成事实。",
                    "suggested_fix": "改成未来计划或明确标注“拟开展/待验证”；若已有真实数据，提供数据文件、实验记录或可核验来源。",
                    "matched": match.group(0),
                    "full_text_available": full_text_available,
                }
            )

    return issues


def format_review_report(issues):
    issues = issues or []
    if not issues:
        return "确定性锚点核查：未发现未核验的具体图表定位或既成实验事实。"
    lines = [f"确定性锚点核查：发现 {len(issues)} 个必须修复的问题。"]
    for i, issue in enumerate(issues, 1):
        lines.append(
            f"{i}. [{issue.get('type')}] 原文：{issue.get('quote')} "
            f"问题：{issue.get('reason')} 修改：{issue.get('suggested_fix')}"
        )
    lines.append("评审必须逐条回应这些问题；修复前不得判定假设达标。")
    return "\n".join(lines)


def build_review_reason(issues):
    issues = issues or []
    if not issues:
        return None
    dimension = "feasibility" if all(
        str(i.get("type", "")).startswith("unverified_") for i in issues
    ) else "evidence"
    quotes = "；".join(_short(i.get("quote") or "", 120) for i in issues[:3])
    fixes = "；".join(_short(i.get("suggested_fix") or "", 120) for i in issues[:3])
    return {
        "dimension": dimension,
        "location": "确定性锚点核查（代码门）",
        "issue": f"存在未经核验的图表/补充材料定位或既成实验事实：{quotes}",
        "suggestion": f"先按以下方向修正并重新核验：{fixes}",
        "expected_gain": 0,
    }


def format_report(state):
    recorded = state.get("anchor_issues")
    if isinstance(recorded, list):
        issues = recorded
    else:
        issues = check_hypothesis(
            state.get("hypothesis") or state.get("best_hypothesis") or "",
            state,
        )
    lines = [
        "# 锚点与预实验核查报告",
        "",
        f"- 发现问题：{len(issues)} 个",
        f"- 放行状态：{state.get('plan_status') or 'in_progress'}",
        "",
    ]
    if not issues:
        lines.append("未发现未核验的具体图表定位或既成实验事实。")
    else:
        for i, issue in enumerate(issues, 1):
            lines.extend(
                [
                    f"## 问题 {i}：{issue.get('type')}",
                    "",
                    f"- 原文：{issue.get('quote')}",
                    f"- 问题：{issue.get('reason')}",
                    f"- 修改方向：{issue.get('suggested_fix')}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def load_state(run_dir):
    path = os.path.join(run_dir, "state.json")
    if not os.path.isfile(path):
        raise FileNotFoundError("missing state.json: " + path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_report(run_dir, out_path=None):
    state = load_state(run_dir)
    out_path = out_path or os.path.join(run_dir, "06_锚点与预实验核查报告.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(format_report(state))
    return out_path


def main():
    parser = argparse.ArgumentParser(description="检查研究计划中的图表、补充材料和预实验锚点")
    parser.add_argument("run_dir", help="包含 state.json 的运行目录")
    parser.add_argument("--out", default="", help="输出 Markdown 路径")
    args = parser.parse_args()
    try:
        path = write_report(args.run_dir, args.out or None)
    except Exception as exc:
        print("[锚点核查] 失败：" + str(exc))
        sys.exit(1)
    print("[锚点核查] 已保存：" + path)


if __name__ == "__main__":
    main()
