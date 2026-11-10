"""tools.py：统一工具架（BaseTool）—— Agent 的"工具箱"

背景：
  前 4 天我们有了三个独立工具（三只眼睛）：
    1. search_web      —— Tavily 搜全网/新闻
    2. search_papers   —— OpenAlex 搜学术论文
    3. crossref_lookup —— CrossRef 按 DOI 查论文+参考文献

  第 5 天把它们统一注册到一个"工具架"上，提供统一入口 call_tool(name, **kwargs)：
    参数校验 + 异常捕获 + 统一返回结构。

  第 7 天（今天）：再加上"长期记忆"两个工具：
    4. remember —— 把重要信息写进记忆文件（下次运行也能想起来）
    5. recall   —— 按关键词从记忆里搜出以前记下的东西

用法：
    python src/tools.py            # 打印已注册的工具清单（不联网）
"""
import json

import search_web
import search_papers
import search_crossref
import memory          # 今天新增：长期记忆模块（读/写 JSON 文件）


# ============ 工具注册表：名字 -> 工具定义 ============
_TOOLS = {}


def register(name, description, parameters, func):
    """把一个工具登记到工具架上。

    name:        工具名（Agent 用这个名字调用）
    description: 给 LLM 看的说明（什么时候该用这个工具）
    parameters:  参数说明（给 LLM 看，格式仿照 JSON Schema）
    func:        真正干活的 Python 函数
    """
    _TOOLS[name] = {
        "description": description,
        "parameters": parameters,
        "func": func,
    }


def call_tool(name, **kwargs):
    """统一入口：按名字调用工具。

    统一做两件事：
    1. 参数校验：必填参数缺了 -> 直接返回错误（不调用）
    2. 异常捕获：函数内部炸了 -> 返回错误（不让整个 Agent 崩掉）

    统一返回结构：
      {"ok": True,  "result": ...}   成功
      {"ok": False, "error": "..."}  失败
    """
    tool = _TOOLS.get(name)
    if tool is None:
        return {"ok": False, "error": f"未知工具：{name}"}

    # --- 参数校验：必填参数必须在 kwargs 里，且非空字符串 ---
    required = tool["parameters"].get("required", [])
    for key in required:
        value = kwargs.get(key)
        if not value or not str(value).strip():
            return {"ok": False, "error": f"缺少必填参数：{key}"}

    # --- 真正调用 + 异常兜底 ---
    try:
        result = tool["func"](**kwargs)
        return {"ok": True, "result": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def list_tools():
    """生成工具清单文本（给 ReAct 的 LLM 看，让它知道能调用什么）"""
    lines = []
    for name, tool in _TOOLS.items():
        lines.append(f"- {name}: {tool['description']}")
        props = tool["parameters"].get("properties", {})
        param_text = "，".join(f"{k}({v.get('description','')})" for k, v in props.items())
        lines.append(f"  参数：{param_text}")
    return "\n".join(lines)


# ============ 三个"翻译层"包装函数 ============
# 统一原则：上游返回什么格式不重要，
# 我们在这里转成干净、统一的字典，交给 Agent 用。

def _web_search(query, max_results=5):
    """包装 Tavily：原始结果 -> 干净列表"""
    results = search_web.search_web(query, max_results=int(max_results))
    cleaned = []
    for r in results:
        cleaned.append({
            "标题": r.get("title"),
            "链接": r.get("url"),
            "摘要": (r.get("content") or "")[:150],
            "发布日期": r.get("published_date"),
        })
    return cleaned


def _paper_search(query, per_page=5):
    """包装 OpenAlex：原始结果 -> 干净列表（复用 paper_to_dict 翻译层）"""
    papers = search_papers.search_papers(query, per_page=int(per_page))
    return [search_papers.paper_to_dict(p) for p in papers]


def _crossref_lookup(doi, max_refs=5):
    """包装 CrossRef：DOI -> 论文信息 + 前几条参考文献"""
    doi = doi.strip()
    # 用户可能给完整的 doi.org 链接，剥掉前缀只留裸 DOI
    for prefix in ("https://doi.org/", "http://doi.org/",
                   "https://dx.doi.org/", "http://dx.doi.org/"):
        if doi.startswith(prefix):
            doi = doi[len(prefix):]
    work = search_crossref.fetch_work(doi)
    info = search_crossref.paper_summary(work)
    refs = []
    for ref in work.get("reference", [])[:max_refs]:
        refs.append(ref.get("article-title") or ref.get("unstructured") or "(无标题)")
    info["参考文献"] = refs
    return info


# ============ 两个"记忆"工具（今天新增） ============

def _remember(content, tags=""):
    """包装：写进长期记忆（tags 是逗号分隔的字符串 -> 拆成列表）"""
    tag_list = [t.strip() for t in str(tags).split(",") if t.strip()] if tags else []
    entry = memory.add_memory(content, tag_list)
    return {"已记住": entry["content"], "记忆编号": entry["id"], "时间": entry["time"]}


def _recall(keyword):
    """包装：按关键词搜长期记忆"""
    hits = memory.search_memory(keyword)
    if not hits:
        return f"记忆里没有找到与「{keyword}」相关的内容"
    return hits


def _data_stats(path):
    """包装 data_stats：读取数据文件，返回清洗与统计分析结果。"""
    import data_stats
    result = data_stats.analyze_file(path)
    return {
        "report": data_stats.render_markdown(result),
        "summary": {
            "shape": result["shape"],
            "numeric_columns": result["numeric_columns"],
            "missing": result["missing"],
            "outliers": result["outliers"],
            "correlations": result["correlations"],
            "chart_suggestions": result["chart_suggestions"],
        },
    }


# ============ 注册六个工具 ============
register(
    name="search_web",
    description="搜索全网新闻和网页，返回最近的结果。适合查「今天有什么新闻/动态」。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词，如 人工智能 大模型"},
            "max_results": {"type": "integer", "description": "返回条数，默认 5"},
        },
        "required": ["query"],
    },
    func=_web_search,
)

register(
    name="search_papers",
    description="搜索学术论文，按关键词返回标题、年份、作者、期刊、被引次数、DOI。",
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "论文关键词，如 fast charging battery degradation"},
            "per_page": {"type": "integer", "description": "返回条数，默认 5"},
        },
        "required": ["query"],
    },
    func=_paper_search,
)

register(
    name="crossref_lookup",
    description="输入一篇论文的 DOI，返回论文信息和它的参考文献列表。用于顺着引用扩展文献池。",
    parameters={
        "type": "object",
        "properties": {
            "doi": {"type": "string", "description": "论文 DOI，如 10.1038/s41560-019-0356-8"},
        },
        "required": ["doi"],
    },
    func=_crossref_lookup,
)

register(
    name="remember",
    description="把一条重要信息写进长期记忆（存到本地 JSON 文件，下次运行也能想起来）。适合记：找到的关键论文、DOI、重要结论。",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要记住的内容，一句话说清楚"},
            "tags": {"type": "string", "description": "可选，逗号分隔的标签，如 电池,论文"},
        },
        "required": ["content"],
    },
    func=_remember,
)

register(
    name="recall",
    description="从长期记忆里搜索过去记下的内容。适合问：之前记过什么、上次找到的论文是什么。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词，如 电池"},
        },
        "required": ["keyword"],
    },
    func=_recall,
)

register(
    name="data_stats",
    description="对上传的实验数据文件（CSV/TSV/JSON/XLSX）做数据清洗与统计分析：缺失值、重复行、异常值（IQR）、描述统计、相关、正态性，并给可视化图表建议。",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "数据文件在本地的绝对路径"},
        },
        "required": ["path"],
    },
    func=_data_stats,
)


if __name__ == "__main__":
    print(f"=== 已注册的工具清单（共 {len(_TOOLS)} 个）===")
    print(list_tools())
    print("\n提示：这里只展示清单；真正的调用入口 call_tool 在 react_agent.py 里使用")
