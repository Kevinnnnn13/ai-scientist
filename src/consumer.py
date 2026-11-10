# -*- coding: utf-8 -*-
"""consumer_test：下游 AI 消费测试（独立模块，批次2-2A）。

作用：把「自包含性」从评审里拆出来单独测——让一个只收到假设文本的下游 AI
判断能否零追问开工写论文。评审不再兼任「自包含」检查，避免双扣与漂移。

用法：
  from consumer import consumer_test
  status, questions, assumptions = consumer_test(hypothesis)
"""
import os
import sys

SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from llm_client import json_chat
except Exception:
    json_chat = None

CONSUMER_SYSTEM = """你是下游论文生成器。你只收到一份研究假设，没有其他任何上下文。
你的任务：判断能否在不追问的情况下，用它写出一篇论文的 Methods 和 Results。

只判断「文本是否自足」：所有关键信息是否在假设文本内给出（术语定义、变量测量方式、实验参数、判定标准、数据来源、样本量）。
不要因「缺少文献引用/文献支撑/新颖性/可规模化」而提问——那些由评审负责，不属于你的职责。

输出：
1. questions：所有你无法自行决定、必须追问才能继续的关键信息。宁多勿漏。
2. assumptions：你虽能自行决定、但属于你主观假设的信息。
3. status：questions 为空 -> "consumable"；否则 -> "needs_clarification"。

规则：不得编造；不得用「通常做法」「文献惯例」代替假设中未给出的信息；宁可多列追问，不可假装能写。
只输出 JSON：{"status": "consumable|needs_clarification", "questions": [string], "assumptions": [string]}"""

CONSUMER_SCHEMA = {
    "type": "object",
    "required": ["status", "questions", "assumptions"],
    "properties": {
        "status": {"type": "string"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
    },
}


def consumer_test(hypothesis, use_json_chat=True):
    """下游 AI 消费测试：只用假设文本。失败保守判 needs_clarification。

    返回 (status, questions, assumptions)；
    status: "consumable" | "needs_clarification"。
    """
    hypothesis = (hypothesis or "").strip()
    if not hypothesis:
        return "needs_clarification", ["（假设为空）"], []
    if json_chat is None or not use_json_chat:
        # 无 LLM 时的保守兜底：按空白信息量粗判
        words = len(hypothesis.split())
        if words < 200:
            return "needs_clarification", ["（文本过短，保守判定需澄清）"], []
        return "consumable", [], []
    try:
        obj = json_chat(hypothesis, system=CONSUMER_SYSTEM, schema=CONSUMER_SCHEMA, max_retries=1)
        status = "consumable" if obj.get("status") == "consumable" else "needs_clarification"
        return status, list(obj.get("questions") or []), list(obj.get("assumptions") or [])
    except Exception as e:
        return "needs_clarification", [f"（消费测试解析失败，保守判定：{str(e)[:80]}）"], []


def format_consumer_report(status, questions, assumptions):
    """给评审 prompt 用的报告段。"""
    lines = ["下游 AI 消费测试报告（独立调用，仅输入假设文本）：",
             f"status：{status}"]
    if questions:
        lines.append("追问清单（视为必须修复项）：")
        for i, q in enumerate(questions, 1):
            lines.append(f"  {i}. {q}")
    if assumptions:
        lines.append("下游 AI 自行假设的部分：")
        for i, a in enumerate(assumptions, 1):
            lines.append(f"  {i}. {a}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    h = sys.argv[1] if len(sys.argv) > 1 else "研究假设：新材料 X 在温度 T 下的导电率提升 20%。"
    s, q, a = consumer_test(h)
    print("status:", s)
    print("questions:", q)
    print("assumptions:", a)
