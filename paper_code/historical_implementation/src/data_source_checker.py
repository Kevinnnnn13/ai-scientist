# -*- coding: utf-8 -*-
"""Generic checks for data-source access, granularity, coverage and observability."""

import argparse
import json
import os
import re
import sys


SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from llm_client import json_chat, extract_json
except Exception:
    json_chat = None
    extract_json = None

try:
    from reviewer_report import _parse_hypotheses
except Exception:
    _parse_hypotheses = None


DATA_SOURCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sources"],
    "properties": {
        "sources": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "kind",
                    "source",
                    "public",
                    "access",
                    "granularity",
                    "coverage",
                    "supports_claimed_use",
                    "risk",
                ],
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["external_dataset", "instrument"],
                    },
                    "source": {"type": "string"},
                    "public": {
                        "type": "string",
                        "enum": ["yes", "no", "unverified", "not_applicable"],
                    },
                    "access": {"type": "string"},
                    "granularity": {"type": "string"},
                    "coverage": {"type": "string"},
                    "supports_claimed_use": {
                        "type": "string",
                        "enum": ["yes", "no", "unverified"],
                    },
                    "risk": {"type": "string"},
                },
            },
        }
    },
}

DATA_SOURCE_SYSTEM = """你是科研方案的「数据源与可观测性」核查员。不要维护或背诵领域事实知识库，而是严格检查方案是否把数据使用说清楚，并判断数据粒度是否足以构造所需变量。

先判定 kind：
- external_dataset：数据库、公开报表、API、名录、外部数据集。
- instrument：实验仪器、测量平台、成像或表征设备、自建实验装置。

核查每个来源：
1. public：
   - external_dataset：明确写公开/开放获取才判 yes；明确私有判 no；其余 unverified。
   - instrument：统一判 not_applicable。
2. access：
   - external_dataset：获取路径、数据库名称、API、下载入口或申请流程；没有明确写就填「未说明」。
   - instrument：仪器型号、平台配置或测量设置；没有明确写就填「未说明」。
3. granularity：
   - external_dataset：机构、交易、事件、日、月、季度、个体、样本等；没有明确写就填「未说明」。
   - instrument：空间分辨率、时间分辨率、采样频率、ROI 或测量单位；没有明确写就填「未说明」。
4. coverage：
   - external_dataset：时间覆盖和更新频率；没有明确写就填「未说明」。
   - instrument：单次测量时长、采样窗口或可覆盖的研究周期；没有明确写就填「未说明」。
5. supports_claimed_use：只根据方案文字判断，该来源的粒度、覆盖和可获取性是否足以直接构造主张所需变量。
   - 只有各要素都明确且足以覆盖分析时才判 yes。
   - 如果方案要求某种层级或时间粒度的变量，但来源只描述为更粗粒度，判 no。
   - 信息不足一律判 unverified，不得用领域名气替代可观测性证据。
6. risk：一句话说明最关键的缺口、错配风险或为什么无法确认。

规则：
- 一个数据库/报告/API/数据集/仪器算一个源，不要按文献计数，也不要按统计检验计数。
- 不要因为某个机构或数据库有名就默认数据一定能支持主张。
- 不要凭外部知识判断仪器真实检测限；只判断方案是否写清了分辨率、范围和变量构造。
- public、access、granularity、coverage 四个字段只能来自方案原文；不得凭记忆补 URL、更新频率、粒度或年份。方案没写就填「未说明」。
- 外部知识只能用于把 supports_claimed_use 从 yes 降为 no 或 unverified，不能用来把方案未写的信息升级为 yes。
- 如果外部知识能明确证明来源缺少主张所需的关键层级或时间粒度，应直接判 no，并在 risk 中说明；只有无法确定时才判 unverified。
- 不确定时选 unverified，不能选 yes。
- 所有解释字段用中文；数据库、仪器、算法等专有名词可保留英文。
- JSON 字段名必须严格使用：kind、source、public、access、granularity、coverage、supports_claimed_use、risk；不得改成中文键。
- 最多返回 12 个源，只输出 JSON。"""


def _norm(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def load_state(run_dir):
    path = os.path.join(run_dir, "state.json")
    if not os.path.isfile(path):
        raise FileNotFoundError("missing state.json: " + path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def hypothesis_text(state):
    return str(state.get("best_hypothesis") or state.get("hypothesis") or "")


def extract_source_snippets(state):
    texts = []
    best = hypothesis_text(state)
    if _parse_hypotheses is not None:
        for _title, sections in _parse_hypotheses(best):
            for label, body in sections:
                if label in ("验证方法", "方法", "数据与方法"):
                    texts.append(body)
    if not texts:
        texts.append(best)
    plan = state.get("research_plan") or {}
    if isinstance(plan, dict):
        texts.append(str(plan.get("verification_design") or ""))
    text = "\n".join(texts)
    text = re.sub(r"[\n；;。]+", "\n", text)
    dataset_re = re.compile(
        r"数据来源|数据来自|数据取自|数据源|数据库|数据集|样本来源|"
        r"公开数据|公开数据库|名单|列表|报告|rates|panel data|trade repository|"
        r"database|data from|repository|dashboard|survey",
        re.I,
    )
    instrument_re = re.compile(
        r"仪器|设备|显微镜|热像仪|"
        r"TOF[-\s]?SIMS|GIWAXS|MOCON|KPFM|SThM|SEM|XRD|XPS|PL[–-]SThM|"
        r"spectrometer|microscope|instrument",
        re.I,
    )
    method_noise_re = re.compile(
        r"统计采用|统计方法|显著性|检验|置信区间|算法|模型|拟合|"
        r"t-test|p\s*[<>=]|regression",
        re.I,
    )
    raw_snippets = []
    seen = set()
    for raw in text.splitlines():
        line = _norm(raw.strip(" -\t"))
        is_dataset = bool(dataset_re.search(line)) and not bool(method_noise_re.search(line))
        is_instrument = bool(instrument_re.search(line)) and bool(
            re.search(r"采用|使用|测试|检测|测量|采集|成像|扫描|完成|with|using", line, re.I)
        )
        if not line or not (is_dataset or is_instrument):
            continue
        parts = [line]
        if is_dataset and re.search(r"数据来源|数据来自|数据集包括|data from|database", line, re.I) and "、" in line:
            split = [_norm(x.strip(" ，,")) for x in line.split("、") if _norm(x.strip(" ，,"))]
            if len(split) > 1:
                parts = split
        for part in parts:
            if part in seen:
                continue
            seen.add(part)
            raw_snippets.append(part)
    return raw_snippets[:16]


def _deterministic_items(snippets):
    items = []
    for snippet in snippets:
        is_instrument = bool(
            re.search(
                r"仪器|设备|显微镜|热像仪|"
                r"TOF[-\s]?SIMS|GIWAXS|MOCON|KPFM|SThM|SEM|XRD|XPS|PL[–-]SThM|"
                r"spectrometer|microscope|instrument",
                snippet,
                re.I,
            )
        )
        kind = "instrument" if is_instrument else "external_dataset"
        checks = []
        public = "not_applicable" if kind == "instrument" else "unverified"
        if kind == "external_dataset" and re.search(r"公开|开放获取|public|open access|可下载|免费获取", snippet, re.I):
            public = "yes"
        elif kind == "external_dataset" and re.search(r"私有|非公开|需申请|proprietary|restricted", snippet, re.I):
            public = "no"
        elif kind == "external_dataset":
            checks.append("是否公开未说明")
        access = "未说明"
        if kind == "instrument" or re.search(
            r"http|www\.|api|portal|repository|数据库|报告|下载|申请",
            snippet,
            re.I,
        ):
            access = snippet
        else:
            checks.append("获取路径未说明")
        granularity = "未说明"
        if re.search(
            r"机构|银行|事件|交易|个体|样本|日|月|季度|年度|分辨率|像素|帧|"
            r"Hz|nm|μm|ROI|扫描面积|q-range|"
            r"firm|bank|event|transaction|daily|monthly|quarterly|annual|resolution",
            snippet,
            re.I,
        ):
            granularity = snippet
        else:
            checks.append("数据粒度未说明")
        coverage = "未说明"
        if re.search(r"(?:19|20)\d{2}|Q[1-4]|年|月|日", snippet):
            coverage = snippet
        else:
            checks.append("时间覆盖未说明")
        items.append(
            {
                "kind": kind,
                "source": snippet,
                "public": public,
                "access": access,
                "granularity": granularity,
                "coverage": coverage,
                "supports_claimed_use": "unverified",
                "risk": "；".join(checks) or "仅使用方案文字完成基础核查，仍需人工确认。",
            }
        )
    return items


def judge_sources(state, snippets):
    if not snippets:
        return []
    if json_chat is None:
        return _deterministic_items(snippets)
    plan = state.get("research_plan") or {}
    verification = plan.get("verification_design", "") if isinstance(plan, dict) else ""
    predictions = plan.get("testable_predictions", "") if isinstance(plan, dict) else ""
    prompt = (
        "原始研究问题：\n"
        + str(state.get("question") or "")
        + "\n\n研究假设：\n"
        + hypothesis_text(state)[:5000]
        + "\n\n验证设计：\n"
        + str(verification)[:2500]
        + "\n\n可检验预测：\n"
        + str(predictions)[:2000]
        + "\n\n请核查以下数据源片段：\n"
        + "\n".join(f"- {item}" for item in snippets)
    )
    data = None
    try:
        data = json_chat(
            prompt,
            system=DATA_SOURCE_SYSTEM,
            schema=DATA_SOURCE_SCHEMA,
            max_retries=1,
        )
    except Exception as exc:
        raw = getattr(exc, "last_content", "") or ""
        parsed = extract_json(raw) if extract_json and raw else None
        if isinstance(parsed, list):
            data = {"sources": parsed}
        elif isinstance(parsed, dict):
            data = parsed
        else:
            return _deterministic_items(snippets)
    items = data.get("sources") if isinstance(data, dict) else []
    normalized = []
    plan_text = "\n".join(snippets)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        source = _norm(
            item.get("source")
            or item.get("来源")
            or item.get("数据源")
            or item.get("名称")
        )
        if not source:
            continue
        public = str(item.get("public") or item.get("是否公开") or "unverified")
        if public == "yes" and not re.search(r"公开|开放获取|public|open access|可下载|免费获取", plan_text, re.I):
            public = "unverified"
        access = _norm(item.get("access") or item.get("获取方式")) or "未说明"
        urls = re.findall(r"https?://\S+", access)
        if urls and not any(url.rstrip(".,;；。") in plan_text for url in urls):
            access = "未说明"
        normalized.append(
            {
                "kind": str(item.get("kind") or item.get("类型") or "external_dataset"),
                "source": source,
                "public": public,
                "access": access,
                "granularity": _norm(item.get("granularity") or item.get("粒度")) or "未说明",
                "coverage": _norm(item.get("coverage") or item.get("时间覆盖")) or "未说明",
                "supports_claimed_use": str(
                    item.get("supports_claimed_use")
                    or item.get("是否支持当前分析")
                    or "unverified"
                ),
                "risk": _norm(item.get("risk") or item.get("风险说明")) or "未说明",
            }
        )
    return normalized or _deterministic_items(snippets)


def _issue(source, issue_type, reason, suggested_fix, severity="review"):
    return {
        "criterion": "方法可行性",
        "type": issue_type,
        "severity": severity,
        "quote": source,
        "reason": reason,
        "suggested_fix": suggested_fix,
    }


def build_issues(items, snippets):
    issues = []
    if not snippets:
        return [
            _issue(
                "（未提取到数据源说明）",
                "missing_data_source",
                "验证设计中未提取到可核查的数据源说明。",
                "逐项写明数据源、是否公开、获取方式、粒度、时间覆盖和统计单位。",
                "fail",
            )
        ]
    for item in items:
        source = item.get("source", "")
        kind = item.get("kind", "external_dataset")
        if item.get("supports_claimed_use") == "no":
            issues.append(
                _issue(
                    source,
                    "instrument_observability_mismatch" if kind == "instrument" else "data_granularity_mismatch",
                    "来源粒度或覆盖不足以直接构造当前主张所需变量：" + item.get("risk", ""),
                    "更换能提供所需观测粒度的来源，或收窄主张并重新定义可观测变量。",
                    "fail",
                )
            )
        missing = []
        if kind == "external_dataset" and item.get("public") == "no":
            missing.append("访问受限且未说明申请流程")
        elif kind == "external_dataset" and item.get("public") == "unverified":
            missing.append("是否公开未说明")
        for label, value in (
            ("获取方式", item.get("access")),
            ("数据粒度", item.get("granularity")),
            ("时间覆盖", item.get("coverage")),
        ):
            if not value or value == "未说明":
                missing.append(label + "未说明")
        if missing:
            if kind == "instrument":
                issue_type = "instrument_observability_unverified"
            else:
                issue_type = "data_access_unverified" if item.get("public") == "no" else "data_metadata_missing"
            issues.append(
                _issue(
                    source,
                    issue_type,
                    "；".join(missing) + "。无法确认该来源能直接支持当前分析。",
                    "为每个来源补充公开状态、获取方式、粒度、覆盖和变量构造方式；无法确认时标为“未验证”。",
                )
            )
        elif item.get("supports_claimed_use") == "unverified":
            issues.append(
                _issue(
                    source,
                    "instrument_observability_unverified" if kind == "instrument" else "data_use_unverified",
                    "无法确认该来源能直接支持当前分析：" + item.get("risk", ""),
                    "补充粒度、覆盖、变量构造方式和获取路径；无法确认时标为“未验证”。",
                )
            )
    return issues


def run_checks(run_dir, use_llm=True):
    state = load_state(run_dir)
    snippets = extract_source_snippets(state)
    items = judge_sources(state, snippets) if use_llm else _deterministic_items(snippets)
    return build_issues(items, snippets), items, state


def render_markdown(issues, items, state, run_dir):
    by_type = {}
    for issue in issues:
        by_type[issue["type"]] = by_type.get(issue["type"], 0) + 1
    lines = [
        "# 数据源与可观测性核查报告",
        "",
        f"- 运行目录：{run_dir}",
        f"- 研究问题：{state.get('question', '')}",
        f"- 识别数据源：{len(items)}",
        f"- 发现问题：{len(issues)}",
        "",
    ]
    if not items:
        lines.append("未提取到可核查的数据源说明。")
    else:
        lines.append("## 数据源清单")
        lines.append("")
        for idx, item in enumerate(items, 1):
            lines.append(f"### {idx}. {item.get('source', '')}")
            lines.append("")
            lines.append(f"- 类型：{item.get('kind', '')}")
            lines.append(f"- 是否公开：{item.get('public', '')}")
            lines.append(f"- 获取方式：{item.get('access', '')}")
            lines.append(f"- 数据粒度：{item.get('granularity', '')}")
            lines.append(f"- 时间覆盖：{item.get('coverage', '')}")
            lines.append(f"- 是否支持当前分析：{item.get('supports_claimed_use', '')}")
            lines.append(f"- 风险说明：{item.get('risk', '')}")
            lines.append("")
    lines.append("## 问题清单")
    lines.append("")
    if not issues:
        lines.append("未发现明确问题。")
    for idx, issue in enumerate(issues, 1):
        lines.append(f"### {idx}. {issue['type']} ({issue.get('severity', 'review')})")
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


def write_data_source_report(run_dir):
    issues, items, state = run_checks(run_dir)
    md = render_markdown(issues, items, state, run_dir)
    md_path = os.path.join(run_dir, "数据源与可观测性核查报告.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)
    json_path = os.path.join(run_dir, "数据源与可观测性核查.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"run_dir": run_dir, "sources": items, "issues": issues},
            f,
            ensure_ascii=False,
            indent=2,
        )
    return md_path


def main():
    parser = argparse.ArgumentParser(description="Check data-source observability in a completed run.")
    parser.add_argument("run_dir")
    parser.add_argument("--no-llm", action="store_true", help="Use deterministic checks only")
    args = parser.parse_args()
    if args.no_llm:
        issues, items, state = run_checks(args.run_dir, use_llm=False)
        md = render_markdown(issues, items, state, args.run_dir)
        out_path = os.path.join(args.run_dir, "数据源与可观测性核查报告.md")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(md)
        print(out_path)
    else:
        print(write_data_source_report(args.run_dir))


if __name__ == "__main__":
    main()
