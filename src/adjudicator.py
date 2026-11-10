# -*- coding: utf-8 -*-
"""质疑甄别节点 v1（Adjudicator）—— 判断用户追问/质疑是否值得采纳。

设计原则（与用户讨论确定）：
- 轻标准：只做分类（合理/部分合理/不合理/无法判断）+ 拆出可采纳部分，不搞四维评分。
- 保守降级：无法判断 / LLM 失败 / 非法输出一律不进生成器（宁可漏、不可毒）。
- 强制具体理由：rationale 必须引用假设或质疑的原文片段，防"糊弄式判定"。
- 复用 llm_client.json_chat（JSON 模式 + schema 校验 + 自动重试，temperature=0）。

用法（合并进项目后）：
    from adjudicator import adjudicate
    result = adjudicate(question, best_hypothesis, user_text)
    # result: {verdict, rationale, accepted_questions, rejected_reasons, error?}
"""
import sys
import os

ADJUDICATE_SYSTEM = """你是「AI Scientist」系统里的用户质疑甄别器。你的职责是判断用户对科学假设的质疑/修改建议是否值得采纳，防止不合理或误导性的意见破坏系统的稳定性。

判定四维度：
1. 科学合理性：质疑/建议是否符合已知科学事实与基本逻辑？是否建立在明显的错误认识上？
2. 关联性：是否针对当前假设的实际内容（背景依据/明确主张/预期结果/验证方法/判定标准）？还是与假设无关的泛泛而谈？
3. 可操作性：建议是否具体、可落地（具体指标、具体方法、具体修改位置）？
4. 误导风险：若采纳，是否会把假设带偏（要求编造文献、删除关键证据、改成错误的结论、夸大结论等）？

判定规则：
- 任一条质疑存在明显科学错误或明显误导风险 → verdict=不合理，rejected_reasons 给出具体拒绝理由。
- 部分内容合理、部分不合理 → verdict=部分合理；accepted_questions 只保留合理部分（可改写得更精确）；rejected_reasons 列出被拒部分。
- 与假设无关、纯情绪表达、空泛无内容 → verdict=不合理。
- 无法证实对错（信息不足）→ verdict=无法判断，accepted_questions 留空（宁可不采纳，也不能带偏）。
- 注意「不合理」与「无法判断」的区别：不合理=明确有错或有毒；无法判断=不知道对不对且无法证实。
- 判定合理时必须拆出 accepted_questions（至少 1 条）；rewritten 可以比原文更精确、可执行，但不能改变原意。

只输出 JSON，格式：
{"verdict": "合理|部分合理|不合理|无法判断", "rationale": "整体判断理由，须引用假设或质疑中的原文片段，禁止空话", "accepted_questions": [{"original": "用户原文片段", "rewritten": "采纳后改写"}], "rejected_reasons": [{"original": "用户原文片段", "reason": "拒绝理由"}]}"""

ADJUDICATE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["verdict", "rationale", "accepted_questions", "rejected_reasons"],
    "properties": {
        "verdict": {"type": "string"},
        "rationale": {"type": "string"},
        "accepted_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["original", "rewritten"],
                "properties": {"original": {"type": "string"}, "rewritten": {"type": "string"}},
            },
        },
        "rejected_reasons": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["original", "reason"],
                "properties": {"original": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
    },
}

_VERDICTS = ("合理", "部分合理", "不合理", "无法判断")


def _norm_verdict(v):
    if v in _VERDICTS:
        return v
    return "无法判断"


def _clean_items(items, fields):
    """把 LLM 返回的条目列表规范化：过滤非 dict、缺失字段、空字符串。"""
    out = []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        row = {}
        ok = True
        for f in fields:
            val = it.get(f)
            if not isinstance(val, str) or not val.strip():
                ok = False
                break
            row[f] = val.strip()
        if ok:
            out.append(row)
    return out


def adjudicate(question, hypothesis, user_text, llm=None, hypothesis_limit=4000):
    """对用户质疑做合理性甄别。

    返回 dict：
      verdict           合理 / 部分合理 / 不合理 / 无法判断
      rationale         判断理由（可能为空字符串）
      accepted_questions 采纳后的质疑列表 [{"original","rewritten"}]（供评审/生成器消费）
      rejected_reasons   被拒理由列表 [{"original","reason"}]
      error              处理异常时的说明（正常为 ""）

    保守降级：
      - 输入为空          -> 不合理（不调用 LLM）
      - LLM 异常/超时     -> 无法判断（不进生成器）
      - verdict=合理 但没拆出 accepted -> 把整条原文作为 accepted（合理意见不丢）
      - verdict=部分合理 但 accepted 为空 -> 视为不合理（没拆出任何可采纳内容）
    """
    text = str(user_text or "").strip()
    if not text:
        return {"verdict": "不合理", "rationale": "用户未输入内容",
                "accepted_questions": [], "rejected_reasons": [], "error": ""}

    hyp = str(hypothesis or "")
    if len(hyp) > hypothesis_limit:
        hyp = hyp[:hypothesis_limit] + "\n…（节选）"

    prompt = f"""研究问题：{str(question or '').strip()}

当前最佳假设（节选）：
{hyp}

用户质疑/建议：
{text}

请按系统规则判断，只输出 JSON。"""

    if llm is not None:
        # 注入的 llm（离线 mock / 外部测试）：按 json_chat 同款签名调用
        try:
            data = llm(prompt, system=ADJUDICATE_SYSTEM, schema=ADJUDICATE_SCHEMA, max_retries=1)
        except Exception as exc:
            return {"verdict": "无法判断", "rationale": "甄别调用失败：%s" % exc,
                    "accepted_questions": [], "rejected_reasons": [], "error": str(exc)}
    else:
        # 生产路径：不走 json_chat 的严格 schema 校验（空数组在此是合法输出），
        # 直接 temperature=0 + JSON 模式 + extract_json + 代码内自规范化。
        try:
            src_dir = os.path.dirname(os.path.abspath(__file__))
            if src_dir not in sys.path:
                sys.path.insert(0, src_dir)
            import llm_client as _lc
            client, model = _lc.get_client()
            backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()
            extra = {} if backend == "ollama" else {"response_format": {"type": "json_object"}}
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": ADJUDICATE_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0,
                **extra,
            )
            try:
                _lc._acc_usage(getattr(resp, "usage", None))
            except Exception:
                pass
            data = _lc.extract_json(resp.choices[0].message.content)
        except Exception as exc:
            return {"verdict": "无法判断", "rationale": "甄别调用失败：%s" % exc,
                    "accepted_questions": [], "rejected_reasons": [], "error": str(exc)}

    if not isinstance(data, dict):
        return {"verdict": "无法判断", "rationale": "甄别输出非 JSON 对象",
                "accepted_questions": [], "rejected_reasons": [], "error": "bad output"}

    verdict = _norm_verdict(data.get("verdict"))
    rationale = str(data.get("rationale") or "").strip()
    accepted = _clean_items(data.get("accepted_questions"), ("original", "rewritten"))
    rejected = _clean_items(data.get("rejected_reasons"), ("original", "reason"))

    # 后置规则
    if verdict == "合理" and not accepted:
        accepted = [{"original": text, "rewritten": text}]
    if verdict == "部分合理" and not accepted:
        verdict = "不合理"
    if verdict == "不合理" and not rejected:
        rejected = [{"original": text, "reason": rationale or "未给出具体拒绝理由"}]

    return {"verdict": verdict, "rationale": rationale,
            "accepted_questions": accepted, "rejected_reasons": rejected, "error": ""}


if __name__ == "__main__":
    # 命令行自测：python adjudicator.py "<question>" "<hypothesis>" "<user_text>"
    q = sys.argv[1] if len(sys.argv) > 1 else "测试问题"
    h = sys.argv[2] if len(sys.argv) > 2 else "假设：A 与 B 正相关，拟用实验 C 验证。"
    u = sys.argv[3] if len(sys.argv) > 3 else "这个假设不成立。"
    import json
    print(json.dumps(adjudicate(q, h, u), ensure_ascii=False, indent=2))