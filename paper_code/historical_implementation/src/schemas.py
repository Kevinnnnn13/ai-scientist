"""schemas.py：科学假设报告的 12 字段 JSON Schema —— 后续所有 Agent 的公共契约"""

HYPOTHESIS_SCHEMA = {
    "type": "object",
    "properties": {
        "标题":        {"type": "string", "description": "一句话研究标题"},
        "摘要":        {"type": "string", "description": "2~3 句话概括研究内容与结论"},
        "问题":        {"type": "string", "description": "要解决的具体科学问题"},
        "思路":        {"type": "string", "description": "核心研究思路（怎么做）"},
        "技术手段":     {"type": "array", "items": {"type": "string"}, "description": "用到的技术，如 特征工程/时序模型/机器学习"},
        "数据集":      {"type": "string", "description": "使用的数据集名称与来源"},
        "Source":     {"type": "string", "description": "源变量（特征 / 自变量）"},
        "Target":     {"type": "string", "description": "目标变量（预测对象 / 因变量）"},
        "方法论":      {"type": "string", "description": "方法框架，如 监督学习 / 时序建模 / 对比实验"},
        "实验设计":    {"type": "string", "description": "数据划分、评价指标、对照实验安排"},
        "结果":        {"type": "string", "description": "预期结果或已观察到的结果"},
        "参考文献":     {"type": "array", "items": {"type": "string"}, "description": "相关文献或参考资料"},
    },
    "required": [
        "标题", "摘要", "问题", "思路", "技术手段", "数据集",
        "Source", "Target", "方法论", "实验设计", "结果", "参考文献",
    ],
    "additionalProperties": False,   # 不允许 Schema 之外的字段
}

# 放进 system 角色，让模型时刻记住输出纪律
SYSTEM_HINT = (
    "你是一个严谨的科研助手。输出 JSON 时你必须严格遵守以下纪律：\n"
    "1. 只输出一个 JSON 对象，不要输出任何解释、前言或后记；\n"
    "2. 不要用 ```json 代码块包裹，直接输出 JSON 本身；\n"
    "3. 字段名必须严格等于要求中给出的字段名，一个不多、一个不少；\n"
    "4. 数组字段至少包含 2 个字符串元素；\n"
    "5. 所有字段值只允许字符串或字符串数组，不允许嵌套对象。\n"
)

# ============ 第 4 天新增：每日新闻 digest 的 Schema ============

NEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "日期": {"type": "string", "description": "聚合日期，如 2026-08-03"},
        "主题": {"type": "string", "description": "本期主题，如 AI 领域今日要闻"},
        "新闻列表": {
            "type": "array",
            "description": "精选新闻，最多 10 条",
            "items": {
                "type": "object",
                "properties": {
                    "标题": {"type": "string"},
                    "一句话摘要": {"type": "string", "description": "不超过 40 字"},
                    "为什么值得关注": {"type": "string", "description": "站在大学生读者角度解释价值"},
                    "来源链接": {"type": "string", "description": "必须来自原始材料"},
                },
                "required": ["标题", "一句话摘要", "为什么值得关注", "来源链接"],
            },
        },
    },
    "required": ["日期", "主题", "新闻列表"],
    "additionalProperties": False,
}