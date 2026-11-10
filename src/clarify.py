# -*- coding: utf-8 -*-
"""clarify.py：追问精修闸门 —— 安全检测之后、进主流程之前

作用：
  1. 判断用户问题是否需要追问（白名单/清晰自洽 -> 不需要；模糊/多义 -> 需要）
  2. 需要时生成 2-3 个针对性追问，让提问者补充细节
  3. 把原始问题 + 追问 Q&A 合并成「问题精修上下文」，喂给知识整合

设计约定（2026-08-28 与用户确认）：
  - Science 125 白名单 + 清晰问题：快通道，不追问（0 成本）
  - 追问可选：前端提供「跳过追问」按钮（api 层用 skip_clarify）
  - 只补充、不改写原始问题（保持可追溯）
  - LLM 失败时 fail-open：不追问，直接进主流程
"""
import os
import sys

from logger import get_logger

SRC = os.path.dirname(os.path.abspath(__file__))

# 环境变量 SAFETY_GUARD_LLM=0 同样关闭追问判断（离线自测/演示用）
ENABLE_LLM = os.getenv("SAFETY_GUARD_LLM", "1").strip() != "0"


_CLARIFY_SYSTEM = """你是「AI Scientist」科研系统的问题精修助理。系统会把用户问题直接送去做文献检索与假设生成：追问能让输入更准，但也会增加用户负担，所以要克制。

判断是否需要追问：
1. 不需要追问（need_clarify=false）：问题本身清晰、自洽、可检验；或属于公认的经典科学问题（如《Science》125 问这类）；或用户已上传论文、问题与论文指向明确。此时 questions 必须为空数组。
2. 需要追问（need_clarify=true）：问题存在以下任一情况——
   - 关键术语/研究对象不明确（指代不清、领域不明、缺主语）
   - 缺少约束条件（时间/空间/对象范围、数据来源、学科视角）
   - 目标不明确（用户想要机制解释、预测模型、还是优化方案）
   - 题目过大需要聚焦（如"如何治愈癌症"这类需要缩小范围的问题）
   - 与上传论文结合时存在未明确的衔接点
   此时生成 2-3 条追问，每条都必须是「用户能直接回答的具体细节问题」，禁止模板化空泛问题。

输出严格 JSON：
{"need_clarify": true 或 false, "questions": ["...", "..."], "reason": "一句话中文说明"}
- need_clarify=false 时 questions 必须为 []
- 追问必须针对该具体问题写"""


_CLARIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "need_clarify": {"type": "boolean"},
        "questions": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    # questions 不设必填：need_clarify=false 时模型合法输出空数组，
    # 而 llm_client 的校验器会把"空数组"判为错误（见 validate_against_schema）。
    "required": ["need_clarify", "reason"],
}


def needs_clarification(question, papers=None):
    """判断是否需要追问。返回 {"need_clarify": bool, "questions": [...], "reason": str}。"""
    question = (question or "").strip()
    if not question:
        return {"need_clarify": False, "questions": [], "reason": "空输入，无需追问"}

    # 白名单（Science 125）直接快通道，0 成本
    try:
        sys.path.insert(0, SRC)
        import safety_guard
        if safety_guard.is_whitelisted(question):
            return {"need_clarify": False, "questions": [], "reason": "白名单问题，无需追问"}
    except Exception:
        pass

    if not ENABLE_LLM:
        return {"need_clarify": False, "questions": [], "reason": "追问判断未启用（SAFETY_GUARD_LLM=0）"}

    text = question
    if papers:
        excerpt = "\n\n".join((str(p) or "")[:800] for p in papers)
        text += "\n\n【用户上传的论文节选】\n" + excerpt[:3000]

    try:
        sys.path.insert(0, SRC)
        import llm_client
        obj = llm_client.json_chat(
            "请判断下面这条输入是否需要追问（它可能是科研问题）：\n\n" + text[:6000],
            system=_CLARIFY_SYSTEM,
            schema=_CLARIFY_SCHEMA,
            max_retries=1,
        )
    except Exception as e:
        get_logger("guard").warning("追问判断 LLM 异常，走快通道：%s", e)
        return {"need_clarify": False, "questions": [], "reason": "追问判断暂时不可用，已直接运行"}

    need = bool(obj.get("need_clarify"))
    questions = obj.get("questions") or []
    if not isinstance(questions, list):
        questions = []
    questions = [str(x).strip() for x in questions if str(x).strip()][:3]
    if need and not questions:
        need = False  # 模型说需要但没给出问题 -> 视为不需要，避免卡住用户
    return {"need_clarify": need, "questions": questions, "reason": str(obj.get("reason") or "")}


def merge_clarification(question, qa):
    """把原始问题 + 追问 Q&A 合并成精修上下文（不改写原问题，可追溯）。"""
    lines = ["原始问题：" + str(question or "").strip()]
    if qa:
        lines.append("【用户补充说明（追问环节获得，仅作参考）】")
        for i, item in enumerate(qa, 1):
            q = str(item.get("question") or "").strip()
            a = str(item.get("answer") or "").strip()
            if q or a:
                lines.append("%d. 追问：%s" % (i, q or "（未显示）"))
                lines.append("   用户补充：%s" % (a or "（未作答）"))
    return "\n".join(lines)


if __name__ == "__main__":
    import json as _json
    q = sys.argv[1] if len(sys.argv) > 1 else "How to cure cancer?"
    print(_json.dumps(needs_clarification(q), ensure_ascii=False, indent=2))
