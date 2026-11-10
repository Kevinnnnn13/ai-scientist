# -*- coding: utf-8 -*-
"""证据链模块：把假设拆成逐条主张，标注证据类别与依据（独立模块）。

对应赛题「证据梳理」环节：每条主张标出
  - category：文献支持 / 新主张（本假设提出） / 有争议 / 反证
  - evidence：支撑文献标题（只能来自给定文献池）
  - confidence：高/中/低

用法：
  from evidence_chain import build_evidence_chain
  chain = build_evidence_chain(hypothesis, literature, knowledge_tree_text)
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

EVIDENCE_SYSTEM = """你是证据链构建器。把给定研究假设拆成逐条「主张」，每条主张标注证据类别。
证据类别定义：
- literature_supported：该主张是领域已有共识/有文献直接支持
- new_claim：该主张是本假设新提出的（文献未直接支持，属于可检验预测）
- debated：该主张在领域内有争议
- contradicted：该主张与已知文献结论冲突（这类要特别标出）

规则：
1. 每条主张必须短句（一句话），能独立检验；
2. evidence 只能从给定文献列表里选标题，逐字对应，禁止编造；
3. 每条给出 confidence（high/medium/low）；
4. 无法归类的写「依据不足」并说明。
只输出 JSON：{"claims": [{"claim": str, "category": str, "evidence": [str], "confidence": str, "note": str}]}"""

EVIDENCE_SCHEMA = {
    "type": "object",
    "required": ["claims"],
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["claim", "category", "evidence", "confidence", "note"],
                "properties": {
                    "claim": {"type": "string"},
                    "category": {"type": "string"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
        }
    },
}


def _lit_titles(literature):
    titles = []
    for p in literature or []:
        if isinstance(p, dict):
            t = p.get("标题") or p.get("title") or ""
        else:
            t = str(p)
        if str(t).strip():
            titles.append(str(t).strip())
    return titles


def build_evidence_chain(hypothesis, literature=None, knowledge_tree_text="", use_llm=True):
    """返回 evidence_chain dict；LLM 失败时返回基于关键词的保守降级。"""
    if json_chat is None or not use_llm:
        return _fallback_chain(hypothesis)
    titles = _lit_titles(literature)
    prompt = f"""研究假设：
{hypothesis[:4000]}

给定文献（仅标题，禁止新增）：
{chr(10).join('- ' + t for t in titles[:40]) or '（空）'}

知识树摘要（作为领域背景参考）：
{knowledge_tree_text[:1500] or '（无）'}"""
    try:
        obj = json_chat(prompt, system=EVIDENCE_SYSTEM, schema=EVIDENCE_SCHEMA, max_retries=2)
        claims = obj.get("claims") or []
        return {"claims": claims, "ok": True}
    except Exception as e:
        return {"claims": _fallback_chain(hypothesis).get("claims", []), "ok": False, "error": str(e)[:120]}


def _fallback_chain(hypothesis):
    """无 LLM 兜底：把假设按句切分，全部标 new_claim。"""
    claims = []
    for sent in str(hypothesis or "").replace("\n", " ").split("。"):
        sent = sent.strip()
        if len(sent) >= 10:
            claims.append({"claim": sent[:200], "category": "new_claim",
                           "evidence": [], "confidence": "low", "note": "（降级：无 LLM，待人工确认）"})
    return {"claims": claims[:12], "ok": True, "degraded": True}


def fmt_chain(chain):
    lines = ["## 证据链"]
    for i, c in enumerate((chain or {}).get("claims") or [], 1):
        lines.append(f"{i}. [{c.get('category')}] {c.get('claim')} —— 置信度 {c.get('confidence')}")
        for e in c.get("evidence") or []:
            lines.append(f"   依据：{e}")
        if c.get("note"):
            lines.append(f"   注：{c['note']}")
    return "\n".join(lines) or "（无证据链）"


if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else "钙钛矿太阳能电池的稳定性提升 20%。"
    c = build_evidence_chain(h, use_llm=False)
    print(fmt_chain(c))
