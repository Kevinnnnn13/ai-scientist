# -*- coding: utf-8 -*-
"""工具选型模块：假设 → 自动匹配验证工具/技术手段/数据/实验设计。

对应赛题 12 字段里的「必要的技术手段 / 数据集 / 实验设计」，
以及用户点名的「生成假设后选取工具」。

设计：
- 内置 TOOL_LIB（验证手段类别 → 具体工具/方法 + 适用场景关键词）
- select_tools(hypothesis)：按关键词规则 + LLM 精修，返回结构化选型
- 输出可直接写入 12 字段研究计划
"""
import os
import sys
import re

SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
try:
    from llm_client import json_chat
except Exception:
    json_chat = None

# 工具库：类别 → {name, keywords(命中即推荐), example}
TOOL_LIB = [
    {"category": "统计分析", "name": "假设检验（t 检验/卡方/ANOVA/Wilcoxon）",
     "keywords": ["显著", "差异", "相关", "对比", "p值", "显著性", "均值"],
     "example": "两组实验数据用独立样本 t 检验，报告 95% CI"},
    {"category": "回归建模", "name": "线性/逻辑回归（sklearn/statsmodels）",
     "keywords": ["预测", "回归", "斜率", "趋势", "关系", "拟合"],
     "example": "自变量 X 对因变量 Y 的线性回归，检验斜率显著性"},
    {"category": "数值模拟", "name": "仿真/数值计算（numpy/scipy/ODE）",
     "keywords": ["模拟", "仿真", "模型", "计算", "方程", "机制", "动力学"],
     "example": "构建常微分方程模型，数值求解并扫参数"},
    {"category": "机器学习", "name": "分类/回归模型（sklearn 基线 + 评估指标）",
     "keywords": ["机器学习", "分类", "特征", "训练", "准确率", "F1", "AUC"],
     "example": "训练分类器并对比基线，报告 F1/AUC"},
    {"category": "数据检索", "name": "公开数据集/数据库（OpenAlex/Crossref/领域库）",
     "keywords": ["数据集", "数据", "样本", "观测", "统计资料"],
     "example": "从公开数据库获取样本，注明来源与筛选条件"},
    {"category": "实验方案", "name": "对照实验设计（分组/重复/样本量）",
     "keywords": ["实验", "对照", "样本量", "重复", "分组", "测量"],
     "example": "设置实验组/对照组，每组 N 个样本，3 次重复"},
    {"category": "文献证据", "name": "文献综述与元分析（证据等级评估）",
     "keywords": ["文献", "综述", "证据", "机制"],
     "example": "系统检索文献，按证据等级汇总支持/反对证据"},
]


def _rule_match(hypothesis):
    hits = []
    for item in TOOL_LIB:
        kws = item["keywords"]
        score = sum(1 for k in kws if k in hypothesis)
        if score > 0:
            hits.append({"category": item["category"], "name": item["name"],
                         "example": item["example"], "match_score": score})
    hits.sort(key=lambda x: -x["match_score"])
    return hits


SELECT_SYSTEM = """你是实验方案设计助手。给定一个科学假设，选出一套验证它的「工具方案」。
输出四部分：
- techniques：验证所需的技术手段（2-4 项，具体到方法/工具，如「配对 t 检验（scipy）」「有限元仿真（COMSOL）」）
- datasets：需要的数据集/数据来源（来源要真实可查，注明类型：公开库/实测采集/仿真生成）
- experiments：实验设计要点（分组、样本量、重复次数、基线对照、评估指标）
- rationale：为什么这样选（1-2 句）

规则：不许编造不存在的工具/数据源名称；如不确定数据源，写「需检索确认」。
只输出 JSON：{"techniques": [str], "datasets": [str], "experiments": [str], "rationale": str}"""

SELECT_SCHEMA = {
    "type": "object",
    "required": ["techniques", "datasets", "experiments", "rationale"],
    "properties": {
        "techniques": {"type": "array", "items": {"type": "string"}},
        "datasets": {"type": "array", "items": {"type": "string"}},
        "experiments": {"type": "array", "items": {"type": "string"}},
        "rationale": {"type": "string"},
    },
}


def select_tools(hypothesis, literature=None, use_llm=True):
    """返回选型 dict：{techniques, datasets, experiments, rationale, rule_hits}"""
    rule_hits = _rule_match(hypothesis or "")
    if json_chat is not None and use_llm:
        lit = ""
        for p in literature or []:
            t = p.get("标题") or p.get("title") or "" if isinstance(p, dict) else str(p)
            if str(t).strip():
                lit += "- " + str(t).strip() + "\n"
        prompt = f"""研究假设：\n{hypothesis[:3000]}\n\n可用文献（仅标题）：\n{lit[:1200] or '（无）'}"""
        try:
            obj = json_chat(prompt, system=SELECT_SYSTEM, schema=SELECT_SCHEMA, max_retries=2)
            obj["rule_hits"] = rule_hits
            return obj
        except Exception:
            pass
    # 降级：规则匹配
    return {
        "techniques": [h["name"] for h in rule_hits[:4]] or ["（规则未命中，需人工补充）"],
        "datasets": ["（需检索确认公开数据集）"],
        "experiments": ["（需人工补充实验设计）"],
        "rationale": "基于关键词规则自动选型，未用 LLM 精修",
        "rule_hits": rule_hits,
    }


def fmt_selection(sel):
    lines = ["## 工具选型（验证方案）"]
    lines.append("**技术手段**：" + "；".join(sel.get("techniques") or []))
    lines.append("**数据集**：" + "；".join(sel.get("datasets") or []))
    lines.append("**实验设计**：")
    for e in sel.get("experiments") or []:
        lines.append(f"- {e}")
    lines.append(f"**选型理由**：{sel.get('rationale')}")
    return "\n".join(lines)


if __name__ == "__main__":
    h = sys.argv[1] if len(sys.argv) > 1 else "新材料的加入使电池循环寿命显著提升（p<0.05）。"
    s = select_tools(h, use_llm=False)
    print(fmt_selection(s))
