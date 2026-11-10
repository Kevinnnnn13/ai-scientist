"""langgraph_agent.py：用 LangGraph 写"真的" ReAct Agent（联网版）

和 langgraph_demo.py 的区别只有一处：假 LLM/假工具 -> 真 chat()/真 call_tool()。
图的结构一模一样：llm 节点 -> 路由 -> tool 节点 -> 回到 llm -> ... -> END。

跑法：
  python docs/day8/langgraph_agent.py "你的问题"
"""
import copy
import difflib
import hashlib
import io
import json
import os
import re
import sys
import time

import matplotlib
matplotlib.use("Agg")                       # 不弹窗口，直接存文件（终端友好）
import matplotlib.pyplot as plt

from langgraph.graph import StateGraph, START, END

from llm_client import chat, extract_json, json_chat, JsonChatError, get_last_json_perf
import llm_client
from state import AgentState          # 从 state.py 里请登记表进来
from tools import call_tool, list_tools
import search_papers
import human_loop
import consumer
import anchor_checker
# ===== 质疑甄别节点（Adjudicator）：判断用户质疑/修改建议是否值得采纳（内联，自 _adjudicator.py）=====
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

try:
    from semantic_search import title_semantic_scores, term_anchor, SEMANTIC_KEEP_MIN, SEMANTIC_STRONG
except Exception:
    title_semantic_scores = None
    term_anchor = None
    SEMANTIC_KEEP_MIN = 0.16
    SEMANTIC_STRONG = 0.25

MAX_STEPS = 5   # 安全阀：最多跑几轮

RUN_LOG = []    # 运行日志收集：缺口分析/假设生成/评审的原文，结束时写入 Markdown
def _safe_print(text, limit=6000):
    """打印可能含特殊字符的 LLM 原文；遇到编码/管道异常时退回 ASCII 转义并截断，绝不让打印中断运行。"""
    try:
        print(text)
    except Exception:
        try:
            safe = str(text).encode("ascii", "backslashreplace").decode("ascii")
            if len(safe) > limit:
                safe = safe[:limit] + "...(truncated)"
            print(safe)
        except Exception:
            pass



def _write_progress(state, stage, detail="", round_no=None):
    """把当前阶段进度写到 progress.json（API 前端实时展示用）。

    优先写 API 通过环境变量 PROGRESS_FILE 指定的文件；没有则写运行文件夹。
    附带上累计 token 用量与按账户均价估算的金额（¥）。
    """
    folder = (state or {}).get("run_folder")
    path = os.environ.get("PROGRESS_FILE") or (os.path.join(folder, "progress.json") if folder else None)
    if not path:
        return
    try:
        u = llm_client.get_usage()
        pt = int(u.get("prompt_tokens", 0) or 0)
        ct = int(u.get("completion_tokens", 0) or 0)
        total = pt + ct
        rate = float(os.getenv("AI_COST_CNY_PER_M", "0.24"))
        data = {"stage": stage, "detail": detail, "round": round_no,
                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                "tokens": total, "cost_cny": round(total * rate / 1000000.0, 6),
                "prompt_tokens": pt, "completion_tokens": ct}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass

# 运行结果日志目录：默认 27日/生成日志；设置 AI_LOG_DIR 可隔离到独立目录
#（用于稳定性测试/多实例并行，避免 _运行序号.txt 无锁竞争）
_ENV_LOG_DIR = os.environ.get("AI_LOG_DIR", "").strip()
if _ENV_LOG_DIR:
    LOG_DIR = _ENV_LOG_DIR
elif getattr(sys, "frozen", False):
    LOG_DIR = os.path.join(os.path.dirname(sys.executable), "27日", "生成日志")  # exe 同目录
else:
    LOG_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "26暑假", "27日", "生成日志")  # 开发模式

# ============ 系统提示词：告诉 LLM 能干什么、怎么输出 ============
SYSTEM = f"""你是一个科研助手 Agent，可以调用以下工具：

{list_tools()}

工作方式（每轮严格按此格式输出）：
要么是"行动"：
Thought: 你现在在思考什么
Action: 工具名
Action Input: {{"参数名": "参数值"}}

要么是"收尾"：
Thought: 你已经得到足够信息了
Final Answer: 你的最终答案

规则：
1. 每轮只能输出一个 Action 或直接 Final Answer；
2. 工具结果会以 Observation 的形式返回给你；
3. 得到足够信息后，必须用 Final Answer 结束；
4. 最多 {MAX_STEPS} 轮。"""


# ============ 从 LLM 输出里抠出（工具名, 参数）============
def parse_action(text):
    m = re.search(r"Action:\s*(.+?)\s*Action Input:\s*(\{.*\})", text, re.S)
    if not m:
        return None
    name = m.group(1).strip().strip('"\'')
    try:
        args = json.loads(m.group(2))
    except json.JSONDecodeError:
        return None
    if not isinstance(args, dict):
        return None
    return name, args


# ============ Node 1：问 LLM 下一步（真联网） ============
def call_llm(state):
    prompt = f"用户问题：{state['question']}\n"
    if state["history"]:
        prompt += "\n之前的经过：\n" + "\n".join(state["history"])
    if state.get("feedback"):                        # 上级回传指令（如"文献为空，回去补搜"）
        prompt += f"\n\n上级反馈：{state['feedback']}\n请先按这条反馈行动，再决定下一步。"
    prompt += "\n\n请输出你的下一步。"
    reply = chat(prompt, system=SYSTEM)          # 真 LLM 调用
    _safe_print(f"\n[LLM] {reply}")
    updates = {"history": state["history"] + [reply], "steps": state["steps"] + 1, "feedback": ""}
    if "final answer" in reply.lower():
        updates["search_requested"] = False   # P9：软搜索请求被消费（LLM 决定不搜也算消费，防循环）
    return updates

# ============ Node 2：执行工具（真工具） ============
def call_tool_node(state):
    last = state["history"][-1]                  # 最新一条 LLM 输出
    parsed = parse_action(last)                  # 抠出要调什么工具、什么参数
    name = None                     # 先占位：万一解析失败，后面用 name 才不会崩
    result = None                   # 同理
    if parsed is None:
        obs = "输出无法解析，请直接给出 Final Answer 或重新输出 Action。"
    else:
        name, args = parsed
        print(f"-> 调用工具 {name}，参数：{args}")
        result = call_tool(name, **args)         # 真工具
        obs = json.dumps(result, ensure_ascii=False)
        if len(obs) > 2000:
            obs = obs[:2000] + "……(已截断)"
    print(f"-> Observation：{obs[:300]}{'……' if len(obs) > 300 else ''}")

    updates = {"history": state["history"] + [f"Observation: {obs}"]}
    if name in ("search_papers", "search_web"):
        updates["search_requested"] = False           # P9：搜索动作发生，软搜索请求视为已消费
        n_total = state.get("total_soft_searches", 0) + 1
        updates["total_soft_searches"] = n_total      # 全局软搜次数，只增不减（防“文献一变就清零”绕过预算）
        new_lit = result.get("result") if isinstance(result, dict) else None
        if isinstance(new_lit, list):
            # L6（N5）：无关文献不进池（进 filtered_out 日志）——池=相关文献不变量，
            # 否则 data_score 与 cdr 信号打架；软搜索修复：新文献【合并】进池而非整体替换。
            q = args.get("query") if isinstance(args, dict) else ""
            # 语义兜底：搜索词与标题同义改写（强语义匹配）也放行；语义层失败则行为不变
            _sem_scores = {}
            if title_semantic_scores is not None and q:
                try:
                    _sem_scores = title_semantic_scores(
                        [str(_p.get("标题") or _p.get("title") or "").strip()
                         for _p in new_lit if isinstance(_p, dict)], q) or {}
                except Exception:
                    _sem_scores = {}
            filtered = []
            related = []
            for _p in new_lit:
                if not isinstance(_p, dict):
                    continue
                _t = str(_p.get("标题") or _p.get("title") or "").strip()
                if _paper_relevant_query(q, _t):
                    related.append(_p)
                elif _sem_scores.get(_t, 0.0) >= SEMANTIC_STRONG:
                    related.append(_p)
                else:
                    filtered.append(_p)
            if filtered:
                updates["filtered_out"] = state.get("filtered_out", []) + [
                    {"round": state.get("rounds", 0), "query": str(q)[:80],
                     "title": str(_p.get("标题") or _p.get("title") or "")[:120]} for _p in filtered]
                RUN_LOG.append({"stage": "搜索过滤", "note": f"无关文献 {len(filtered)} 篇未进池（query={str(q)[:50]}）"})
            old_keys = {_paper_key(_p) for _p in state.get("literature", [])}
            merged = []
            seen = set()
            for _p in list(state.get("literature", [])) + related:
                if not isinstance(_p, dict):
                    continue
                key = _paper_key(_p)
                if key not in seen:
                    seen.add(key)
                    merged.append(_p)
            updates["literature"] = merged
            # L6：相关新增 = 本轮进池且此前不在池里的相关文献数（cdr 语义：相关新增=0）
            new_relevant = sum(1 for _p in related if _paper_key(_p) not in old_keys)
            updates["last_new_relevant"] = new_relevant
            # L7（N4）：相关新增 >=3 且 >= 池 50% -> 标记待重拆（llm 路由时送回 knowledge 节点）
            if _tree_rebuild_needed(new_relevant, len(merged)):
                updates["tree_rebuild_pending"] = True
                RUN_LOG.append({"stage": "知识树", "note": f"相关新增 {new_relevant} 达重拆阈值（池 {len(merged)} 篇）"})
            cur_hash = json.dumps(merged, ensure_ascii=False, sort_keys=True)
        else:
            cur_hash = json.dumps(state.get("literature", []), ensure_ascii=False, sort_keys=True)
        if cur_hash != state.get("prev_literature_hash", ""):
            updates["soft_search_rounds"] = 0         # 文献池变化 -> 连续未变计数归零（仅此重置）
            updates["prev_literature_hash"] = cur_hash
        else:
            updates["soft_search_rounds"] = state.get("soft_search_rounds", 0) + 1   # 文献未变 -> 连续累计
        combined = n_total + state.get("total_data_rounds", 0)
        if combined >= MAX_TOTAL_SEARCH or updates["soft_search_rounds"] >= MAX_SOFT_SEARCH:
            updates["search_exhausted"] = True        # 总预算耗尽 或 同缺口连续 2 轮无新文献 -> 缺口已确认
        elif cur_hash != state.get("prev_literature_hash", ""):
            updates["search_exhausted"] = False
    return updates

# ============ 知识整合：问题 → 概念树 → 逐节点检索 → 缺口标注 ============
# 设计（v1，2026-08-09）：
#   「探险家地图」：把科学问题拆成子问题/知识点，每个知识点挂上检索到的文献，
#   标出知识缺口（gap）。这张地图同时喂给：生成器（找假设生长点）和评审（核依据）。
#   首轮做完整拆解+检索；后续轮幂等：文献变化时纯代码重算覆盖状态，不重复烧 LLM。
MAX_KNOWLEDGE_NODES = 8      # 知识整合：最多拆几个子问题/知识点
MAX_PAPERS_PER_NODE = 5      # 知识整合：每个知识点最多挂几篇文献

KNOWLEDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "root_question": {"type": "string"},
        "analysis": {"type": "string"},
        "sub_problems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "name": {"type": "string"},
                    "concepts": {"type": "array", "items": {"type": "string"}},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "search_keywords": {"type": "array", "items": {"type": "string"}},
                    "verifiable_angles": {"type": "array", "items": {"type": "string"}},
                    "open_debate": {"type": "boolean"},
                },
                "required": ["id", "name", "concepts", "search_keywords"],
            },
        },
    },
    "required": ["root_question", "analysis", "sub_problems"],
}

KNOWLEDGE_SYSTEM = """你是一名科研问题分析师。任务：把给定的科学问题拆解成一棵「知识树」，为后续检索文献和生成可验证的科学假设做准备。

# 输出结构（JSON）
- root_question：原样保留用户问题
- analysis：2-3 句问题分析——这个问题属于哪类科学问题（机制/预测/优化/分类…）、核心未知在哪、要回答它通常需要哪些层面的知识
- sub_problems：3-8 个子问题/知识点，每个代表理解这个问题或验证相关假设所需的一个独立知识面

# 拆解要求
1. 覆盖不同层面，尽量不重叠：例如「现象与机制」「方法/技术/测量」「数据与基准」「前沿与争议」；
2. 每个子问题必须给出：
   - concepts：核心概念（2-4 个）
   - aliases：同义/英文别名（用于匹配文献，可为空数组）
   - search_keywords：检索关键词（英文优先，可直接用于论文数据库检索；要具体，能命中标题/摘要，禁止「science」「research」这类空泛词）。
     若原始问题为中文，每个关键词写成「英文关键词 | 中文关键词」双语形式（用 | 分隔）：英文用于国际文献检索，中文用于中文文献池检索。
   - verifiable_angles：可检验角度（1-3 个，说明该知识面可以通过什么数据/实验/计算被验证）
   - open_debate：布尔值——该知识面在现有文献中是否仍存在未解决的争议/没有定论（true=有争议/未解决，false=已有公认结论）。这是判断「知识缺口 vs 假设生长点」的关键，必须认真判断，不要一律 true 或一律 false。
3. 质量优先，宁缺毋滥：只保留对「理解问题、生成可验证假设」真正必要的知识面；
4. id 从 1 开始连续编号。
只输出 JSON 对象。"""


# ============ 论文输入模块（2026-08-26）：≤3 篇论文 → 知识卡 → 跨篇融合 ============
PAPER_TEXT_LIMIT = 15000          # 每篇论文最多喂给 LLM 的字符数（优先取开头：摘要/引言/结论）

PAPER_CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "标题": {"type": "string"},
        "一句话主旨": {"type": "string"},
        "核心主张": {"type": "array", "items": {"type": "string"}},
        "方法与数据": {"type": "array", "items": {"type": "string"}},
        "关键结论": {"type": "array", "items": {"type": "string"}},
        "局限性": {"type": "array", "items": {"type": "string"}},
        "关键概念": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["标题", "一句话主旨", "核心主张", "方法与数据", "关键结论", "局限性", "关键概念"],
}

PAPER_CARD_SYSTEM = """你是一名论文精读助手。任务：把用户提供的一篇论文全文，压缩成一张结构化的「论文知识卡」，供后续跨论文融合、缺口分析与假设生成使用。

# 输出（JSON，字段必须齐全）
- 标题：论文标题（或你的命名）
- 一句话主旨：一句话概括这篇论文做了什么、得到什么
- 核心主张：2-5 条，论文的核心断言/发现（每条一句话）
- 方法与数据：2-4 条，用的方法、数据/样本来源、实验或分析手段
- 关键结论：2-4 条，明确结论（含方向/量级/阈值等可量化信息）
- 局限性：1-3 条，作者声明或你判断的局限
- 关键概念：3-8 个，论文涉及的核心概念/术语（含英文别名），用于和知识树节点匹配

要求：忠实原文，禁止编造；只输出 JSON 对象。"""

PAPER_FUSION_SCHEMA = {
    "type": "object",
    "properties": {
        "共识点": {"type": "array", "items": {"type": "string"}},
        "矛盾点": {"type": "array", "items": {"type": "string"}},
        "互补点": {"type": "array", "items": {"type": "string"}},
        "共同缺口": {"type": "array", "items": {"type": "string"}},
        "融合后的知识框架": {"type": "string"},
    },
    "required": ["共识点", "矛盾点", "互补点", "共同缺口", "融合后的知识框架"],
}

PAPER_FUSION_SYSTEM = """你是一名跨论文综合分析师。任务：把多张「论文知识卡」融合成一个统一的知识框架，供科研假设生成使用。

# 输出（JSON，字段必须齐全）
- 共识点：≥2 篇论文共同支持的方向/结论（逐条）
- 矛盾点：论文之间互相冲突或证据打架的地方（逐条；这是假设生成的重点生长点）
- 互补点：一篇论文的方法/数据补了另一篇的缺口（逐条）
- 共同缺口：所有论文都没有覆盖、但对研究问题关键的方向（逐条）
- 融合后的知识框架：一段话，概括这些论文组合后形成的整体知识图景（概念、方法、结论、未解决处）

要求：只基于给定知识卡，禁止编造；只输出 JSON 对象。"""


def _user_paper_matches(sp, d):
    """用户论文的「关键概念」是否命中知识树节点的概念/别名（双向子串匹配）。"""
    concepts = [str(x).lower() for x in (sp.get("concepts") or []) + (sp.get("aliases") or [])]
    keys = [str(x).lower() for x in (d.get("概念") or [])]
    for k in keys:
        if not k or len(k) < 2:
            continue
        for c in concepts:
            if not c:
                continue
            if k in c or c in k:
                return True
    return False


def _user_paper_dict(card, idx):
    """把论文知识卡转成 literature 池里的论文条目（带全文要点，标记用户提供）。"""
    def _arr(x):
        if isinstance(x, list):
            return "；".join(str(i) for i in x if str(i).strip())
        return str(x or "")

    title = str(card.get("标题") or f"用户论文 {idx}").strip()
    digest = "；".join(x for x in (
        _arr(card.get("一句话主旨")), _arr(card.get("核心主张")),
        _arr(card.get("方法与数据")), _arr(card.get("局限性")),
    ) if x)
    return {
        "标题": title,
        "作者": "用户提供",
        "期刊": "用户提供",
        "年份": "",
        "DOI": "",
        "来源": "用户提供",
        "摘要": digest,
        "概念": card.get("关键概念") or [],
        "user_paper": True,
    }


def parse_papers(state):
    """论文解析节点（仅当用户提供了论文时生效）：
    每篇论文 → 结构化「论文知识卡」；跨篇融合 → 共识/矛盾/互补/共同缺口。"""
    papers = [str(x).strip() for x in (state.get("given_papers") or []) if str(x).strip()]
    if not papers or state.get("paper_parse_done"):
        return {}
    _write_progress(state, "论文解析", f"解析 {len(papers)} 篇论文 → 知识卡 → 跨篇融合")
    cards = []
    for i, ptext in enumerate(papers, 1):
        try:
            card = json_chat(
                f"第 {i} 篇论文（共 {len(papers)} 篇）全文如下，请按系统提示词输出论文知识卡 JSON：\n{ptext[:PAPER_TEXT_LIMIT]}",
                system=PAPER_CARD_SYSTEM, schema=PAPER_CARD_SCHEMA, max_retries=2,
            )
        except JsonChatError as e:
            card = extract_json(e.last_content) if e.last_content else None
        if isinstance(card, dict) and card.get("核心主张"):
            card.setdefault("标题", f"用户论文 {i}")
            cards.append(card)
        _safe_print(f"\n[论文解析] 第 {i} 篇：{(card.get('标题') if isinstance(card, dict) else '解析失败')}")
    fusion = {}
    if cards:
        try:
            fusion = json_chat(
                "以下是解析出的论文知识卡：\n" + json.dumps(cards, ensure_ascii=False, indent=2),
                system=PAPER_FUSION_SYSTEM, schema=PAPER_FUSION_SCHEMA, max_retries=2,
            )
        except JsonChatError as e:
            fusion = extract_json(e.last_content) if e.last_content else {}
    if not isinstance(fusion, dict):
        fusion = {}
    for k in ("共识点", "矛盾点", "互补点", "共同缺口"):
        fusion.setdefault(k, [])
    fusion.setdefault("融合后的知识框架", "")
    _write_progress(state, "论文解析",
                    f"解析 {len(cards)} 篇，共识 {len(fusion.get('共识点', []))} / 矛盾 {len(fusion.get('矛盾点', []))} / 缺口 {len(fusion.get('共同缺口', []))}")
    RUN_LOG.append({"stage": "论文解析", "text": "融合框架：" + json.dumps(fusion, ensure_ascii=False)})
    return {"paper_cards": cards, "paper_fusion": fusion, "paper_parse_done": True, "status": "论文解析"}


def format_knowledge_tree(tree):
    """把知识树格式化成给生成器/评审看的文本（人类与 LLM 都易读）。"""
    if not isinstance(tree, dict):
        return "（无知识树）"
    lines = [f"根问题：{tree.get('root_question', '')}"]
    if tree.get("analysis"):
        lines.append(f"问题分析：{tree['analysis']}")
    for sp in tree.get("sub_problems", []):
        cov = sp.get("coverage", "")
        tag = {"covered": "✓已覆盖", "partial": "△部分覆盖", "gap": "✗缺口"}.get(cov, "")
        if sp.get("open_debate"):
            tag = (tag + " ◇争议" if tag else "◇争议")
        lines.append(f"- [{sp.get('id')}] {sp.get('name', '')} {tag}")
        if sp.get("concepts"):
            lines.append(f"  概念：{'、'.join(sp['concepts'])}")
        if sp.get("verifiable_angles"):
            lines.append(f"  可检验角度：{'；'.join(sp['verifiable_angles'])}")
        papers = sp.get("papers", [])
        if papers:
            lines.append(f"  文献（{len(papers)} 篇）：")
            for p in papers[:MAX_PAPERS_PER_NODE]:
                title = p.get("标题") or p.get("title") or "无标题"
                journal = p.get("期刊") or p.get("journal") or ""
                year = p.get("年份") or p.get("year") or ""
                src = "（用户提供）" if p.get("user_paper") else ""
                lines.append(f"    - 《{title}》{src}（{journal} {year}）")
        else:
            lines.append("  文献：暂无（知识缺口）")
    return "\n".join(lines)



_EN_CN_SYN = {
    "aging": "老化", "ageing": "老化", "degradation": "降解 退化 老化", "stability": "稳定性 稳定",
    "efficiency": "效率", "crystallization": "结晶", "nucleation": "成核", "defect": "缺陷",
    "carrier": "载流子", "morphology": "形貌", "solvent": "溶剂", "film": "薄膜",
    "device": "器件", "recombination": "复合", "moisture": "湿度 水分", "thermal": "热",
    "residue": "残留", "recovery": "回收", "lifetime": "寿命", "performance": "性能",
    "intermediate": "中间相", "annealing": "退火", "crystal": "结晶", "grain": "晶粒",
}


def _involved_tokens(sp):
    """节点的命中词：英文名/概念/别名 + 常见英文术语的中文近义补充（假设正文多为中文）。"""
    raw = [sp.get("name", "")] + list((sp.get("concepts") or []) + (sp.get("aliases") or []))
    out = []
    for t in raw:
        t = str(t or "").strip().lower()
        if not t:
            continue
        out.append(t)
        for en, cn in _EN_CN_SYN.items():
            if en in t:
                out.extend(c for c in cn.split() if c)
    return out


def _tree_has_gap_or_debate(tree, hypothesis=""):
    """知识树里是否存在「假设涉及」的非全覆盖节点（✗缺口 / △部分覆盖 / ◇争议 / 未标注）。
    evidence 松绑的代码兜底依据：松绑必须「假设涉及的核心概念全部 ✓已覆盖 且无争议」；
    只拦截与假设相关的缺口/争议节点——缺口节点的名称/概念/别名出现在假设文本里才算涉及；
    无知识树或假设为空时保守按不满足处理（不松绑）。"""
    if not isinstance(tree, dict) or not tree.get("sub_problems"):
        return True          # 无知识树 → 无法确认全覆盖 → 不松绑
    hyp = str(hypothesis or "").lower()
    for sp in tree.get("sub_problems", []):
        if sp.get("open_debate") or sp.get("coverage") != "covered":
            if not hyp:
                return True  # 假设为空 → 保守不松绑
            tokens = _involved_tokens(sp)
            if any(str(t).strip().lower() and str(t).strip().lower() in hyp for t in tokens):
                return True  # 假设涉及该缺口/争议节点 → 拦截
    return False


def _tree_gap_debate_nodes(tree, hypothesis=""):
    """列出知识树中非全覆盖节点（用于 03 文档的 evidence 88 解释）。
    传入假设文本时只列「假设涉及的」节点，与封顶判定口径一致；假设为空时列全部。"""
    out = []
    if not isinstance(tree, dict):
        return out
    hyp = str(hypothesis or "").lower()
    for sp in tree.get("sub_problems", []):
        marks = []
        cov = sp.get("coverage", "")
        if cov == "gap":
            marks.append("✗缺口")
        elif cov == "partial":
            marks.append("△部分覆盖")
        elif cov != "covered":
            marks.append("未标注")
        if sp.get("open_debate"):
            marks.append("◇争议")
        if not marks:
            continue
        if hyp:
            tokens = _involved_tokens(sp)
            if not any(str(t).strip().lower() and str(t).strip().lower() in hyp for t in tokens):
                continue  # 与假设无关的缺口/争议节点不列入解释
        out.append(f"[{sp.get('id')}] {sp.get('name', '')}（{'、'.join(marks)}）")
    return out


def apply_evidence_basis(dims, declared_basis, tree, hypothesis=""):
    """evidence 松绑/封顶的代码兜底（2026-08-09）：
    - 评审声明 "covered_all"：知识树全部 ✓已覆盖 且无 ◇争议/✗缺口 → evidence 允许到 92；
      若知识树实际存在争议/缺口 → 强制按 has_gap_or_debate 处理（封顶 88）；
    - 评审声明 "has_gap_or_debate"（或涉及争议/缺口）→ evidence 封顶 88；
    - 未声明 evidence_basis → 不干预（维持评审原值，仅记录）。
    返回 (evidence, effective_basis, capped, reason)。"""
    ev = int(dims.get("evidence") or 0)
    basis = declared_basis if declared_basis in ("covered_all", "has_gap_or_debate") else None
    capped = False
    reason = ""
    if basis == "covered_all":
        if _tree_has_gap_or_debate(tree, hypothesis):
            basis = "has_gap_or_debate"
            capped = True
            reason = "评审声明 covered_all，但知识树存在 ◇争议/✗缺口/部分覆盖，强制按 has_gap_or_debate 封顶 88"
            ev = min(ev, 88)
        elif ev > 92:
            ev = 92
            capped = True
            reason = "covered_all 松绑上限 92"
    elif basis == "has_gap_or_debate" and ev > 88:
        ev = 88
        capped = True
        reason = "涉 ◇争议/✗缺口，evidence 封顶 88"
    return ev, basis, capped, reason

def _paper_relevant(title, sp):
    """标题相关性过滤：标题必须命中该节点的概念/别名短语（原样小写子串匹配）。
    用于去掉「检索词太宽」带回的不相关文献，避免污染文献池与依据核对。"""
    title = str(title or "").lower()
    if not title:
        return False
    phrases = []
    for t in (sp.get("concepts") or []) + (sp.get("aliases") or []):
        t = str(t).strip().lower()
        if len(t) >= 3:
            phrases.append(t)
    if not phrases:
        return True                      # 节点没有可用的概念/别名，不过滤
    return any(p in title for p in phrases)


def _semantic_rescue(title, sp, scores):
    """语义兜底（embedding/TF-IDF）：子串过滤未命中时，强语义匹配直接保留；
    中语义需词干锚点（防无关文献被通用 n-gram 误救）。失败返回 False（行为不变）。"""
    if title_semantic_scores is None or term_anchor is None:
        return False
    sc = scores.get(str(title or "").strip(), 0.0)
    if sc >= SEMANTIC_STRONG:
        return True
    if sc >= SEMANTIC_KEEP_MIN:
        node_texts = ([str(x) for x in (sp.get("concepts") or [])] +
                      [str(x) for x in (sp.get("aliases") or [])] +
                      [str(x) for x in (sp.get("search_keywords") or [])])
        return term_anchor(node_texts, title)
    return False


def _norm_title(t):
    """文献标题归一化（去重用）：小写 + 连字符统一 + 去标点/空白。"""
    if not t:
        return ""
    t = str(t).lower()
    t = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", t)
    return t


def _paper_key(p):
    """文献去重键：归一化标题优先（大小写/标点/空白/连字符变体视为同一篇），DOI 次之，兜底整个 dict 序列化。"""
    t = _norm_title(p.get("标题") or p.get("title") or "")
    if t:
        return "t:" + t
    d = p.get("DOI") or p.get("doi")
    if d:
        return "d:" + str(d).strip().lower()
    return "j:" + json.dumps(p, ensure_ascii=False)


def _coverage_of(papers):
    return "covered" if len(papers) >= 2 else ("partial" if len(papers) == 1 else "gap")


def knowledge_integration(state):
    """知识整合节点（幂等）：
    首轮：拆解问题 → 概念树 → 逐节点检索 → 文献挂树 → 缺口标注；
    后续轮：文献变化时纯代码重算覆盖状态，不重复拆解（省 token）。"""
    _write_progress(state, "知识整合", "拆解问题 → 构建概念树 → 检索文献")
    if not state.get("knowledge_enabled", True):
        # A/B 对照用：关掉知识整合，走昨天的老路径（不拆解、不检索、不标注）
        return {"knowledge_tree": None, "knowledge_gaps": [], "knowledge_done": True,
                "literature": state.get("literature", []), "status": "知识整合（已跳过）",
                "tree_rebuild_pending": False}

    _rebuild = bool(state.get("tree_rebuild_pending"))
    if state.get("knowledge_done") and not _rebuild:
        return _refresh_knowledge_tree(state)
    if _rebuild:
        RUN_LOG.append({"stage": "知识树", "note": "知识树重拆开始（相关新增达标）"})

    question = state.get("question", "")

    # ---- 追问精修：原始问题 + 用户补充说明 一起喂给知识拆解 ----
    prompt_extra = ""
    clarify_qa = state.get("clarify_qa") or []
    if clarify_qa:
        _clines = ["", "【用户补充说明（追问环节获得，仅作参考，不要偏离原问题）】"]
        for _ci, _item in enumerate(clarify_qa, 1):
            _cq = str(_item.get("question") or "").strip()
            _ca = str(_item.get("answer") or "").strip()
            if _cq or _ca:
                _clines.append("%d. 追问：%s" % (_ci, _cq or "（未显示）"))
                _clines.append("   用户补充：%s" % (_ca or "（未作答）"))
        prompt_extra = "\n".join(_clines)
        RUN_LOG.append({"stage": "追问精修", "note": "用户补充了 %d 条追问回答" % len(clarify_qa)})

    # ---- 1. 拆解问题（1 次 LLM，JSON mode + schema 校验）----
    # 语言要求：中文问题 → 关键词双语（英文搜国际文献、中文搜中文文献池，2026-08-30）
    _know_sys = KNOWLEDGE_SYSTEM
    if state.get("question_lang") == "zh":
        _know_sys = KNOWLEDGE_SYSTEM + (
            "\n\n# 语言要求（原始问题为中文）\n"
            "- search_keywords 的每一项必须写成「英文关键词 | 中文关键词」双语形式（用 | 分隔，中间有一个空格）。"
            "英文用于国际文献检索，中文用于中文文献池检索；两者必须是同一概念的中英文表达，不要直译成生硬词。"
        )
    tree = None
    try:
        tree = json_chat(
            f"科学问题：{question}{prompt_extra}\n\n请按系统提示词要求，把这个问题拆解成知识树并输出 JSON。",
            system=_know_sys, schema=KNOWLEDGE_SCHEMA, max_retries=2,
        )
    except JsonChatError as e:
        tree = extract_json(e.last_content) if e.last_content else None

    if not isinstance(tree, dict) or not tree.get("sub_problems"):
        # 兜底：拆解失败就用单节点整体检索，不阻塞流水线
        tree = {
            "root_question": question,
            "analysis": "（自动拆解失败，按整体问题检索）",
            "sub_problems": [{
                "id": 1,
                "name": question[:80],
                "concepts": [question[:40]],
                "aliases": [],
                "search_keywords": [question[:100]],
                "verifiable_angles": [],
            }],
        }

    # ---- 2. 逐节点检索并挂文献 ----
    sub_problems = tree["sub_problems"][:MAX_KNOWLEDGE_NODES]
    seen = set()
    new_lit = []
    # 用户论文预置：转成 literature 条目，并逐节点匹配「论文×知识点覆盖矩阵」
    user_pool = []
    if state.get("paper_cards"):
        for _ui, _card in enumerate(state["paper_cards"], 1):
            user_pool.append(_user_paper_dict(_card, _ui))
    merged = list(state.get("literature", []))
    merged_keys = {_paper_key(p) for p in merged}
    for d in user_pool:
        key = _paper_key(d)
        if key not in merged_keys:
            merged_keys.add(key)
            merged.append(d)
    for sp in sub_problems:
        papers = []
        for d in user_pool:
            if _user_paper_matches(sp, d):
                papers.append(d)
        sp["papers"] = papers
        if len(papers) >= 2:
            # 用户论文已充分覆盖该节点 → 跳过在线检索（省钱，也避免无关文献稀释）
            sp["coverage"] = "covered"
            sp["coverage_note"] = "用户论文覆盖"
            continue
        kw = (sp.get("search_keywords") or [""])[0]
        if kw:
            # 双语关键词拆分（2026-08-30）：英文 | 中文，分别搜英文源与中文文献池
            kw_en = kw.split(" | ")[0].strip()
            kw_zh = kw.split(" | ")[1].strip() if " | " in kw else ""
            try:
                raw = search_papers.search_papers(kw_en, per_page=MAX_PAPERS_PER_NODE)
                cand = [search_papers.paper_to_dict(p) for p in raw]
                if kw_zh:
                    # 中文文献池补充检索（现有源尽力命中中文标题/摘要；未来垂类化接 CNKI 等源）
                    try:
                        raw_zh = search_papers.search_papers(kw_zh, per_page=2)
                        cand += [search_papers.paper_to_dict(p) for p in raw_zh]
                        RUN_LOG.append({"stage": "知识整合", "note": f"节点 {sp.get('id')} 中文文献补充检索（{kw_zh[:40]}）"})
                    except Exception as _zexc:
                        RUN_LOG.append({"stage": "知识整合", "note": f"节点 {sp.get('id')} 中文检索失败（忽略）：{_zexc}"})
                # 语义兜底（embedding/TF-IDF）：子串过滤漏掉但语义相关的文献救回；失败则空 dict，行为不变
                _sem_scores = {}
                if title_semantic_scores is not None and cand:
                    _qtext = " ".join(str(x) for x in (sp.get("concepts") or []) + (sp.get("aliases") or []))
                    try:
                        _sem_scores = title_semantic_scores(
                            [(d.get("标题") or d.get("title") or "") for d in cand], _qtext) or {}
                    except Exception:
                        _sem_scores = {}
                for d in cand:
                    _t = d.get("标题") or d.get("title") or ""
                    if not _paper_relevant(_t, sp):
                        if not _semantic_rescue(_t, sp, _sem_scores):
                            continue    # 相关性过滤：标题不命中概念/别名且语义不匹配的文献不挂树、不进池
                        RUN_LOG.append({"stage": "知识整合", "note": f"语义兜底救回：{str(_t)[:60]}"})
                    key = _paper_key(d)
                    if key in seen:
                        continue
                    seen.add(key)
                    papers.append(d)
                    new_lit.append(d)
            except Exception as exc:
                RUN_LOG.append({"stage": "知识整合", "note": f"节点 {sp.get('id')} 检索失败：{exc}"})
        sp["papers"] = papers
        sp["coverage"] = _coverage_of(papers)
    tree["sub_problems"] = sub_problems

    # ---- 3. 缺口标注 + 合并进 literature（去重，用户论文已在上方预置）----
    gaps = [sp["name"] for sp in sub_problems if sp["coverage"] == "gap"]
    for d in new_lit:
        key = _paper_key(d)
        if key not in merged_keys:
            merged_keys.add(key)
            merged.append(d)

    RUN_LOG.append({"stage": "知识整合", "text": format_knowledge_tree(tree)})
    print(f"\n[知识整合] 拆解出 {len(sub_problems)} 个知识点，文献池 {len(merged)} 篇，缺口 {len(gaps)} 个"
          + ("（知识树重拆）" if _rebuild else ""))
    _write_progress(state, "知识整合",
                    f"拆解出 {len(sub_problems)} 个知识点，文献池 {len(merged)} 篇，缺口 {len(gaps)} 个")
    _tv = state.get("tree_version", 0)
    _mark = ""
    if _rebuild:
        _tv += 1
        # N4：重拆轮分数跳变是「重估非回归」，必须注入标记（评审/生成器各消费一次）
        _mark = f"知识树已更新（version {_tv}），evidence 按新树判定；分数变化可能来自重估而非回归。"
        RUN_LOG.append({"stage": "知识树", "note": f"重拆完成，tree_version -> {_tv}"})
    return {
        "knowledge_tree": tree,
        "knowledge_gaps": gaps,
        "knowledge_done": True,
        "literature": merged,
        "status": "知识整合",
        "tree_version": _tv,
        "tree_rebuild_pending": False,
        "knowledge_tree_mark": _mark,
        "last_new_relevant": len(new_lit),
    }


def _refresh_knowledge_tree(state):
    """后续轮幂等刷新：不调 LLM，只把新增文献按概念/别名关键词挂到树上，重算覆盖状态。"""
    tree = state.get("knowledge_tree")
    if not isinstance(tree, dict) or not isinstance(tree.get("sub_problems"), list):
        return {}
    lit = state.get("literature", [])
    changed = False
    for sp in tree["sub_problems"]:
        owned = list(sp.get("papers", []))
        owned_keys = {_paper_key(p) for p in owned}
        tokens = [str(t).lower() for t in (sp.get("concepts") or []) + (sp.get("aliases") or [])]
        tokens = [t for t in tokens if len(t) >= 2]
        for p in lit:
            key = _paper_key(p)
            if key in owned_keys:
                continue
            title = str(p.get("标题") or p.get("title") or "").lower()
            if any(t in title for t in tokens):
                owned.append(p)
                owned_keys.add(key)
                changed = True
            elif p.get("user_paper") and _user_paper_matches(sp, p):
                owned.append(p)
                owned_keys.add(key)
                changed = True
        sp["papers"] = owned[:MAX_PAPERS_PER_NODE * 2]
        new_cov = _coverage_of(owned)
        if new_cov != sp.get("coverage"):
            sp["coverage"] = new_cov
            changed = True
    if not changed:
        return {}
    gaps = [sp["name"] for sp in tree["sub_problems"] if sp["coverage"] == "gap"]
    return {"knowledge_tree": tree, "knowledge_gaps": gaps}



# ============ 可验证性求证（Data Verify）：达标后对假设逐条主张做验证分析 ============
# 设计（v1，2026-08-09）：
#   无法实际复现实验，所以改成「可验证性求证」：对假设每条核心主张判断能否验证/怎么验证/
#   需要什么数据/可行性/风险，并给出量级估算——对应赛题《科学假设与研究计划》的
#   「实验结果（Results）：通过公式推导或实际执行，在一定范围内验证实验可行性」。
#   位置：评审达标后（route_review -> verify -> END），只对达标假设执行。
DATA_VERIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "verify_method": {"type": "string"},
                    "data_needed": {"type": "string"},
                    "evidence_level": {"type": "string"},
                    "feasibility": {"type": "string"},
                    "risk": {"type": "string"},
                    "verdict": {"type": "string"},
                },
                "required": ["claim", "verify_method", "data_needed", "evidence_level", "feasibility", "risk", "verdict"],
            },
        },
        "results_preview": {"type": "string"},
    },
    "required": ["summary", "claims", "results_preview"],
}

DATA_VERIFY_SYSTEM = """你是一名科研方法学评审专家，负责对已生成的科学假设做「可验证性求证」（Data Verify）。

背景：我们无法实际复现实验，所以验证方式说明要做的是——对假设中的每条核心主张，判断它「能不能被验证、怎么验证、需要什么数据、可行性如何、主要风险是什么」，并在可行时给出量级估算（公式推导或数量级估计）。这对应赛题《科学假设与研究计划》中的「实验结果（Results）：通过公式推导或实际执行，在一定范围内验证实验可行性」。

输入：科学问题、研究假设（最终版本）、知识树（概念→文献覆盖）、最近评审四维。

输出 JSON：
- summary：整体可验证性结论（2-3 句：假设总体是否可验证、最大障碍是什么）
- claims：对假设逐条主张的验证分析（每条）：
  - claim：主张原文（尽量引用假设原句）
  - verify_method：验证方式（文献实证 / 公式推导 / 数值模拟 / 实验设计，可组合）
  - data_needed：需要的数据或实验（具体到数据源/样本/仪器/时长）
  - evidence_level：证据等级（直接文献支持 / 间接支持 / 理论推导 / 待实验验证）
  - feasibility：可行性（可行 / 需条件 / 难以验证）
  - risk：主要风险与难点（1 句）
  - verdict：结论（可验证 / 部分可验证 / 暂不可验证）
- results_preview：可行性论证与量级估算（对应 Results 字段）：给出可预期的验证结果形态、关键指标的合理量级范围（如预期提升幅度、所需样本量、预计耗时/成本量级）。必须是基于现有文献和常识的合理估计，禁止编造具体实验数字。

要求：
1. claims 覆盖假设的全部核心主张（3-6 条为宜），不要遗漏关键变量或关系；
2. evidence_level 必须对照知识树里的文献，不得凭空说「有文献支持」；
3. 对每个 claim 都要给 verdict，不回避；
4. 任何数字都必须是量级估计，并注明「估计」。
只输出 JSON 对象。"""


def format_verification(verify):
    """把验证报告格式化成可读文本（日志/文档用）。"""
    if not isinstance(verify, dict):
        return "（无验证报告）"
    lines = [f"整体结论：{verify.get('summary', '')}", ""]
    for c in verify.get("claims", []):
        lines.append(f"[{c.get('id', '')}] {c.get('claim', '')}")
        lines.append(f"  验证方式：{c.get('verify_method', '')} ｜ 证据等级：{c.get('evidence_level', '')} ｜ 可行性：{c.get('feasibility', '')}")
        lines.append(f"  需要数据：{c.get('data_needed', '')}")
        lines.append(f"  风险：{c.get('risk', '')}")
        lines.append(f"  结论：{c.get('verdict', '')}")
        lines.append("")
    lines.append(f"可行性论证 / 量级估算（Results 预览）：\n{verify.get('results_preview', '')}")
    return "\n".join(lines)


def build_final_delivery(state):
    """把运行状态整理成不依赖 ReAct 对话历史的最终交付摘要。"""
    question = str(state.get("question") or "").strip() or "（未提供科学问题）"
    plan_status = state.get("plan_status") or "in_progress"
    evidence_status = state.get("evidence_status") or "searching"
    hypothesis = str(state.get("best_hypothesis") or state.get("hypothesis") or "").strip()
    verify = state.get("verification") if isinstance(state.get("verification"), dict) else {}

    def _num(value):
        try:
            if value is None:
                return 0
            return int(value) if float(value).is_integer() else round(float(value), 1)
        except (TypeError, ValueError):
            return value

    def _short(text, limit):
        clean = re.sub(r"\s+", " ", str(text or "")).strip()
        if len(clean) <= limit:
            return clean
        return clean[:limit].rstrip() + "……"

    hypothesis_score = _num(state.get("best_score", state.get("hypothesis_score", 0)))
    data_score = _num(state.get("best_data_score", state.get("data_score", 0)))
    status_label = {
        "validated": "验证通过（证据充分）",
        "exploratory": "探索性完成（证据不足，未验证）",
        "in_progress": "未完成（未达到放行门槛）",
    }.get(plan_status, str(plan_status))

    lines = [
        "# 最终交付",
        "",
        "## 交付状态",
        "",
        f"- **状态**：{status_label}",
        f"- **假设质量**：{hypothesis_score} / 100",
        f"- **原始证据覆盖**：{data_score} / 100",
        f"- **证据状态**：{evidence_status}",
    ]
    release_reason = str(state.get("release_reason") or "").strip()
    if release_reason:
        lines.append(f"- **状态说明**：{release_reason}")
    lines.append("")

    if plan_status == "exploratory":
        lines.extend([
            "> **重要边界**：本方案为探索性方案，证据覆盖不足，不能视为已验证。",
            "> 下列假设与验证设计只能用于指导后续检索、实验设计和同行讨论，不得表述为已经成立的研究结论。",
        ])
    elif plan_status == "validated":
        lines.extend([
            "> **结论边界**：本方案已通过系统当前的假设质量与证据覆盖门槛；",
            "> 这表示方案具备进入验证的条件，不等于真实实验或外部数据已经完成验证。",
        ])
    else:
        lines.extend([
            "> **结论边界**：本次运行尚未达到放行门槛，不应把下列内容作为完整研究结论使用。",
        ])

    lines.extend(["", "## 科学问题", "", question, "", "## 当前最佳假设摘要", ""])
    lines.append(_short(hypothesis, 900) or "（本次运行未形成可用假设）")
    lines.extend(["", "完整假设和验证设计见本次运行目录中的 `02_假设生成.md` 与 `03_可验证性验证.md`。"])

    summary = str(verify.get("summary") or "").strip()
    if summary:
        lines.extend(["", "## 可验证性验证摘要", "", _short(summary, 600)])

    claims = verify.get("claims") if isinstance(verify.get("claims"), list) else []
    if claims:
        lines.extend(["", "### 关键可检验主张", ""])
        for claim in claims[:5]:
            if not isinstance(claim, dict):
                continue
            text = str(claim.get("claim") or "").strip()
            verdict = str(claim.get("verdict") or "").strip()
            if text:
                lines.append(f"- {_short(text, 180)}" + (f"（结论：{verdict}）" if verdict else ""))

    gaps = state.get("knowledge_gaps") if isinstance(state.get("knowledge_gaps"), list) else []
    if gaps or plan_status == "exploratory":
        lines.extend(["", "## 证据缺口与限制", ""])
        if gaps:
            for gap in gaps[:8]:
                gap_text = str(gap or "").strip()
                if gap_text:
                    lines.append(f"- {_short(gap_text, 180)}")
        else:
            lines.append("- 当前检索未形成充分的直接证据覆盖，需补充针对性文献、数据或实验。")

    lines.extend(["", "## 下一步", ""])
    if plan_status == "exploratory":
        lines.extend([
            "- 先补齐能直接支撑核心主张的文献、数据或预实验，再重新运行并争取进入 `validated` 状态。",
            "- 在补充证据前，不要把本研究计划的结果写成已验证事实，也不要把预期值当作实测结果。",
        ])
    elif plan_status == "validated":
        lines.extend([
            "- 按验证设计开展实验或数据分析，并保留对照组、原始数据和判定阈值。",
            "- 用独立数据复核关键主张；若结果不支持，应按预先写明的推翻条件修正假设。",
        ])
    else:
        lines.extend([
            "- 先完成缺失的证据检索或假设修改，再重新评审和放行。",
            "- 当前交付只反映未完成状态，不应作为最终研究结论。",
        ])
    return "\n".join(lines).strip()


def data_verify(state):
    """可验证性求证节点：对达标假设逐条主张做验证分析。"""
    _write_progress(state, "可验证性验证", "对假设逐条主张做验证分析")
    hypothesis = state.get("hypothesis", "") or state.get("best_hypothesis", "")
    question = state.get("question", "")
    if not hypothesis:
        verify = {"summary": "（无假设可验证）", "claims": [], "results_preview": ""}
        delivery_state = dict(state)
        delivery_state["verification"] = verify
        return {"verification": verify,
                "final_answer": build_final_delivery(delivery_state),
                "status": "验证完成"}

    kt_text = format_knowledge_tree(state.get("knowledge_tree"))
    dims = json.dumps(state.get("dimensions") or {}, ensure_ascii=False)
    plan_status = state.get("plan_status") or "in_progress"
    evidence_status = state.get("evidence_status") or "searching"
    release_note = (
        "本方案已通过证据与假设质量门槛。"
        if plan_status == "validated"
        else "本方案为探索性方案，证据覆盖不足；不得把结论写成已验证。"
        if plan_status == "exploratory"
        else "本方案尚未达到放行门槛。"
    )
    prompt = f"""科学问题：{question}

研究假设（最终版本）：
{hypothesis}

方案状态：{plan_status}（{evidence_status}）
状态说明：{release_note}

知识树（概念→文献覆盖，作为证据等级判断依据）：
{kt_text}

最近评审四维：{dims}（bottleneck：{state.get('bottleneck', '')}）

请按系统提示词要求，对假设做可验证性求证并输出 JSON。"""
    verify = None
    try:
        verify = json_chat(prompt, system=DATA_VERIFY_SYSTEM, schema=DATA_VERIFY_SCHEMA, max_retries=2)
    except JsonChatError as e:
        verify = extract_json(e.last_content) if e.last_content else None
    if not isinstance(verify, dict):
        verify = {"summary": "（可验证性分析失败）", "claims": [], "results_preview": ""}
    if plan_status == "exploratory":
        summary = str(verify.get("summary") or "").strip()
        prefix = "本方案为探索性方案，证据覆盖不足，不能视为已验证。"
        if not summary.startswith(prefix):
            verify["summary"] = (prefix + " " + summary).strip()
    delivery_state = dict(state)
    delivery_state["verification"] = verify
    delivery_state["plan_status"] = plan_status
    delivery_state["evidence_status"] = evidence_status
    delivery_state["release_reason"] = state.get("release_reason") or release_note
    RUN_LOG.append({"stage": "可验证性验证", "text": format_verification(verify)})
    print(f"\n[可验证性验证] {str(verify.get('summary', ''))[:80]}")
    return {"verification": verify,
            "final_answer": build_final_delivery(delivery_state),
            "status": "验证完成"}


# ============ 研究计划生成（Research Plan）：知识树 + 假设 + 验证报告 + 文献 -> 12 字段《科学假设与研究计划》 ============
# 设计（v1，2026-08-09）：赛题闭环最后一块。产出「自包含、可直接交给下一个 AI/科研人员执行」的
# 研究计划文档（04_研究计划.md），字段固定 12 个，全部内容必须能在流水线产物中找到出处。
RESEARCH_PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "science_question": {"type": "string"},            # 1 科学问题
        "question_analysis": {"type": "string"},           # 2 问题分析
        "knowledge_map": {"type": "string"},               # 3 证据地图（知识树覆盖状态摘要）
        "core_hypothesis": {"type": "string"},             # 4 核心假设
        "hypothesis_source": {"type": "string"},           # 5 假设来源（对应知识节点/缺口/文献）
        "operational_terms": {"type": "array", "items": {"type": "string"}, "examples": ["γ-戊内酯：绿色溶剂，可检索替代说法 GVL / gamma-valerolactone", "刮涂：溶液法成膜工艺，可检索替代说法 blade coating"]},         # 6 概念操作化
        "testable_predictions": {"type": "array", "items": {"type": "string"}, "examples": ["在 25°C/1 sun 条件下，加入 1 vol% GVL 的钙钛矿薄膜，300 小时后归一化效率 ≥ 80%", "气淬刮涂速率 5-20 mm/s 区间内，成膜缺陷密度随速率升高先降后升，拐点在 ~10 mm/s"]},      # 7 可检验预测
        "verification_design": {"type": "string", "examples": ["数据来源：文献池中 5 篇稳定性测试数据 + 自建 3 组对照样品\n方法：加速老化（85°C/85%RH，IEC 61215 协议）\n对照/基线：无添加剂对照组\n样本量或重复：每组 n=5，3 次独立重复\n统计判据：两独立样本 t 检验，p<0.05"]},         # 8 验证设计
        "expected_results_criteria": {"type": "string", "examples": ["支持：若添加剂组 300h 归一化效率 ≥80% 且显著高于对照组（p<0.05）；推翻：若差异不显著或添加剂组更低。"]},   # 9 预期结果与判定标准
        "risks_and_counterevidence": {"type": "string", "examples": ["已知反证：文献 X 报道 GVL 在高温下分解；替代解释：效率差异可能来自膜厚而非添加剂；主要难点：加速老化条件与户外实际寿命的换算。"]},   # 10 反证与风险
        "gaps_and_open_questions": {"type": "array", "items": {"type": "string"}, "examples": ["缺口一：文献池未覆盖 GVL 在>100°C 下的热稳定性数据", "缺口二：卷对卷工艺下的铅泄漏封装尚无定量比较"]},   # 11 缺口与开放问题
        "references": {"type": "array", "items": {"type": "string"}},                # 12 参考文献
    },
    "required": ["science_question", "question_analysis", "knowledge_map", "core_hypothesis",
                 "hypothesis_source", "operational_terms", "testable_predictions",
                 "verification_design", "expected_results_criteria", "risks_and_counterevidence",
                 "gaps_and_open_questions", "references"],
}

RESEARCH_PLAN_SYSTEM = """你是一名科研助理，负责把流水线已定稿的成果，整理成一份「自包含、可直接交给下一个 AI 或科研人员执行」的《科学假设与研究计划》。

背景：这份计划是科研闭环的最终交付物，会被直接拿去做研究立项或交给下游模型理解。它必须不依赖读者已有的领域背景：每个术语首次出现就地定义或给可检索说法，每条内容都能追溯到输入。

输入（全部来自真实流水线产物，禁止编造）：
- 科学问题、研究缺口分析、知识树（概念→文献覆盖→✗缺口/◇争议）、最终假设（历史最高分版本）、可验证性验证报告、文献池。

输出：严格 JSON，12 个字段（按 Schema；字段值形态必须与下方「字段形态示例」一致）：
1. science_question：科学问题（原样）
2. question_analysis：问题分析（2-3 句：问题类型、核心未知、需要哪些知识层面）
3. knowledge_map：证据地图（知识树覆盖状态摘要：哪些节点已覆盖、哪些有缺口/争议，每类一句话）
4. core_hypothesis：核心假设（最终假设原文）
5. hypothesis_source：假设来源（从哪个知识节点/缺口/哪条文献外推而来）
6. operational_terms：概念操作化。每条写成单条字符串「术语：定义（可检索替代说法：…）」，例如「γ-戊内酯：绿色溶剂，可检索替代说法 GVL / gamma-valerolactone」；禁止写成对象、映射或数字。
7. testable_predictions：可检验预测（写成可测量形式，含变量、方向、量级或阈值）
8. verification_design：验证设计。写成单个字符串，内部用换行分点——数据来源：…；获取方式：…；粒度：…；时间覆盖：…\n方法：…\n对照/基线：…\n统计单位：…\n样本量或重复：…\n统计判据：…；禁止写成嵌套对象。
9. expected_results_criteria：预期结果与判定标准（什么结果支持/推翻假设）
10. risks_and_counterevidence：反证与风险（已知反证、替代解释、主要难点）
11. gaps_and_open_questions：知识缺口与开放问题（文献未覆盖/有争议的部分）。逐条字符串，每条一个缺口或开放问题，禁止合并成一段。
12. references：参考文献（只列输入文献池中的标题原文）

字段形态示例（合法 JSON 片段，字段值必须严格按此形态输出）：
{
  "operational_terms": ["γ-戊内酯：绿色溶剂，可检索替代说法 GVL / gamma-valerolactone", "刮涂：溶液法成膜工艺，可检索替代说法 blade coating"],
  "testable_predictions": ["按 ISOS-L-1 协议老化，刮涂器件 T80 寿命预期 ≥ 1000 小时（对照旋涂 ≥ 800 小时）"],
  "verification_design": "数据来源：…；获取方式：…；粒度：…；时间覆盖：…\n方法：…\n对照/基线：…\n统计单位：…\n样本量或重复：…\n统计判据：…",
  "gaps_and_open_questions": ["缺口一：……", "缺口二：……"]
}

要求：
0. 这是「研究计划/验证方案」，不是已完成的研究结果——实验尚未执行。验证设计（字段8）、预期结果（字段9）一律写成「拟采用/拟验证/预期」，禁止写成「已验证/测得/结果表明」等已完成事实的口吻；预期结果只写「什么结果会支持/推翻假设」的判定标准，不编造具体实验数字，量级估算必须标注「（估计）」。
1. 一切内容必须能在输入中找到出处；拿不准写「文献未覆盖」或「（估计）」并说明，禁止编造数据/方法/结论；
2. 面向下一个 AI 和独立人类评审：自包含优先——术语就地定义、判据可测量、方法可执行；使用短句和清晰分段，避免把多个步骤连续写在一个长句中；
3. 验证设计必须落到可执行层面（数据、方法、对照、样本量、判据），不许写「进行深入研究」这类空话；
4. references 与文献池标题逐一对应，不得新增文献池之外的标题；
5. 区分已知事实与尚未验证的新主张；任何新的定量关系、阈值或机制，都要明确标为待验证。
6. 数据源必须逐项写明是否公开、获取方式、粒度、时间覆盖；无法确认的写「未验证」，不得把未确认能力写成可执行前提。
7. 统计单位、时间窗口、期数、事件数、分组数和总观测数必须一致；重复观测、面板数据和生存数据必须说明依赖结构如何处理。
8. 所有预期数字必须标注来源类型：`[文献值]`、`[推导值]`、`[待标定估计]` 或 `[判定阈值]`；无来源时只写量级范围，禁止伪精确置信区间。
9. 计划必须至少有一个环节直接回答原始问题。预测问题要有样本外测试和预测指标；提升/优化问题要有基线、干预、主要结局和效果判据；机制问题要连接到最终结果指标。
10. references 只列正文实际使用的文献；方法、模型、公式、协议或数据库定义优先引用文献池中的原始出处。原始出处不在池中时，明确写「原始方法出处未在给定文献池中，需外部核验」。
11. 引号内文字必须是可定位的逐字引用；没有页码、章节或段落定位时改成转述。
只输出 JSON 对象。"""


def format_research_plan(plan):
    """把研究计划 JSON 格式化成 Markdown（04_研究计划.md / 控制台用）。"""
    if not isinstance(plan, dict):
        return "（无研究计划）"

    def _arr(v):
        if isinstance(v, list):
            return "\n".join(f"- {str(x)}" for x in v if str(x).strip())
        return str(v or "")

    lines = ["# 科学假设与研究计划", ""]
    lines.append(f"## 1. 科学问题\n\n{plan.get('science_question', '')}")
    lines.append(f"## 2. 问题分析\n\n{plan.get('question_analysis', '')}")
    lines.append(f"## 3. 证据地图\n\n{plan.get('knowledge_map', '')}")
    lines.append(f"## 4. 核心假设\n\n{plan.get('core_hypothesis', '')}")
    lines.append(f"## 5. 假设来源\n\n{plan.get('hypothesis_source', '')}")
    lines.append(f"## 6. 概念操作化\n\n{_arr(plan.get('operational_terms'))}")
    lines.append(f"## 7. 可检验预测\n\n{_arr(plan.get('testable_predictions'))}")
    lines.append(f"## 8. 验证设计\n\n{plan.get('verification_design', '')}")
    lines.append(f"## 9. 预期结果与判定标准\n\n{plan.get('expected_results_criteria', '')}")
    lines.append(f"## 10. 反证与风险\n\n{plan.get('risks_and_counterevidence', '')}")
    lines.append(f"## 11. 知识缺口与开放问题\n\n{_arr(plan.get('gaps_and_open_questions'))}")
    lines.append(f"## 12. 参考文献\n\n{_arr(plan.get('references'))}")
    return "\n\n".join(lines)


def _fallback_research_plan(state):
    """兜底：LLM 生成失败时纯代码组装（能填则填，填不了标「（待补充）」），不整轮作废。"""
    tree = state.get("knowledge_tree")
    verify = state.get("verification") or {}
    return {
        "science_question": state.get("question", ""),
        "question_analysis": (tree or {}).get("analysis", "（待补充）") if isinstance(tree, dict) else "（待补充）",
        "knowledge_map": format_knowledge_tree(tree) if isinstance(tree, dict) else "（无知识树）",
        "core_hypothesis": state.get("best_hypothesis") or state.get("hypothesis", ""),
        "hypothesis_source": state.get("gap", "（待补充）"),
        "operational_terms": ["（LLM 生成失败，操作化定义待补充）"],
        "testable_predictions": ["（LLM 生成失败，可检验预测待补充）"],
        "verification_design": format_verification(verify) if isinstance(verify, dict) else "（待补充）",
        "expected_results_criteria": "（待补充）",
        "risks_and_counterevidence": "（待补充）",
        "gaps_and_open_questions": state.get("knowledge_gaps") or ["（待补充）"],
        "references": [str(p.get("标题") or p.get("title") or "") for p in state.get("literature", [])
                       if str(p.get("标题") or p.get("title") or "").strip()],
    }


def research_plan(state):
    """研究计划节点：知识树 + 最佳假设 + 可验证性报告 + 文献 -> 12 字段《科学假设与研究计划》。"""
    hypothesis = state.get("best_hypothesis") or state.get("hypothesis") or ""
    if not hypothesis:
        plan = None
        text = "（无假设，无法生成研究计划）"
    else:
        kt_text = format_knowledge_tree(state.get("knowledge_tree"))
        verify = state.get("verification") or {}
        verify_text = format_verification(verify) if isinstance(verify, dict) else str(verify)
        papers = format_papers(state.get("literature", []))
        prompt = f"""科学问题：{state['question']}

研究缺口分析：
{state.get('gap', '')}

知识树（概念→文献覆盖，✗缺口/◇争议 节点就是假设生长点）：
{kt_text}

最终假设（历史最高分版本，假设分 {state.get('best_score', 0)}，数据分 {state.get('best_data_score', 0)}）：
{hypothesis}

可验证性验证报告：
{verify_text}

文献池（仅标题/期刊/年份，引用时必须使用标题原文）：
{papers}

请按系统提示词要求，输出 12 字段的《科学假设与研究计划》JSON。"""
        plan = None
        try:
            plan = json_chat(prompt, system=RESEARCH_PLAN_SYSTEM, schema=RESEARCH_PLAN_SCHEMA, max_retries=2)
        except JsonChatError as e:
            plan = extract_json(e.last_content) if e.last_content else None
        if not isinstance(plan, dict):
            plan = _fallback_research_plan(state)
            text = format_research_plan(plan)
            RUN_LOG.append({"stage": "研究计划", "note": "LLM 生成失败，已用代码兜底组装", "text": text})
            print("\n[研究计划] LLM 生成失败，已用代码兜底组装")
            return {"research_plan": plan, "research_plan_text": text, "status": "计划完成"}
        text = format_research_plan(plan)
    RUN_LOG.append({"stage": "研究计划", "text": text})
    print(f"\n[研究计划] 12 字段已生成（{state.get('best_score', 0)} 分假设）")
    return {"research_plan": plan, "research_plan_text": text, "status": "计划完成"}


def generate_plan_from_folder(folder):
    """独立生成 12 字段研究计划（--make-plan 入口）：
    读运行文件夹里的 state.json -> research_plan() -> 写 04_研究计划.md。
    返回 (plan_path, plan_text)；失败返回 (None, 错误信息)。
    """
    state_path = os.path.join(folder, "state.json")
    if not os.path.isfile(state_path):
        return None, f"找不到 {state_path}（该运行可能没有 state.json）"
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)
    out = research_plan(state)
    plan_path = os.path.join(folder, "04_研究计划.md")
    with open(plan_path, "w", encoding="utf-8") as f:
        f.write((out.get("research_plan_text") or "（无研究计划）") + "\n")
    return plan_path, out.get("research_plan_text", "")


GAP_SYSTEM = """你是一个科研助手，负责分析给定论文、找出研究缺口，并把缺口写成「可直接生成假设」的形式。

输入：一批论文（仅标题/期刊/年份）。你只能基于这些信息判断，不得编造论文没有体现的内容。

对每个缺口，按以下五段输出：
- 缺口N：缺什么（数据 / 机制 / 范围 / 方法 / 基准，一句话说清，禁止「研究不足」这类空话）
- 为什么重要：阻碍了什么（1 句）
- 可检验的问题形式：写成一个可用数据/实验回答的问题
- 候选假设方向：1-2 个，具体到变量与可能的关系（供后续假设生成直接用）
- 依据：哪些给定文献标题支持该缺口（每个缺口至少 1 条）

规则：
1. 每个缺口必须能从给定文献中读出依据；文献没覆盖的方向不要凭空创造。
2. 3-6 个缺口为宜，质量优先。
3. 只输出分析结果本身，不要客套话。"""

def frontier_scan_node(state):
    """前沿风向扫描（2026-08-29 旁路模块）：检索最近 N 年约 10 篇论文，LLM 总结最新风向。
    位置：知识整合之后、缺口分析之前。独立于主流程——不进文献池、不碰评审评分；
    搜索/LLM 失败自动跳过（fail-open），绝不影响假设生成主链路。"""
    years = int(state.get("frontier_years") or 3)
    q = state.get("question") or ""
    _write_progress(state, "前沿扫描", f"检索最近 {years} 年领域文献…")
    try:
        import frontier_scan
        fr = frontier_scan.scan_frontier(q, years=years)
    except Exception as e:
        fr = {"ready": False, "error": f"前沿扫描异常：{e}", "text": ""}
    RUN_LOG.append({"stage": "前沿扫描", "text": fr.get("text") or fr.get("error") or "（无结果）"})
    _safe_print(f"\n[前沿扫描] {'完成' if fr.get('ready') else '跳过'}：{len(fr.get('papers') or [])} 篇 / {years} 年")
    # 落盘：运行文件夹 04_前沿风向.md（前端历史板块后续从这里读）
    folder = state.get("run_folder")
    if folder and os.path.isdir(folder):
        try:
            body = (fr.get("text") or
                    (f"（前沿扫描不可用：{fr.get('error')}）" if fr.get("error") else "（前沿扫描未执行）"))
            with io.open(os.path.join(folder, "04_前沿风向.md"), "w", encoding="utf-8") as f:
                f.write(body)
        except Exception:
            pass
    return {"frontier_ready": bool(fr.get("ready")), "frontier_years": years,
            "frontier_report": fr.get("report"), "frontier_text": fr.get("text"),
            "frontier_papers": fr.get("papers"), "frontier_error": fr.get("error"),
            "status": "前沿扫描"}


def gap_analysis(state):
    _write_progress(state, "缺口分析", "基于文献与知识树分析研究缺口")
    papers = state["literature"]                    # 从白板读上一阶段留下的论文
    if not papers:                                  # 兜底：没有文献也别崩，基于知识树降级
        _tree = state.get("knowledge_tree")
        kt_text = format_knowledge_tree(_tree)
        if isinstance(_tree, dict) and _tree.get("sub_problems") and kt_text:
            # 降级（2026-08-29 稳定性修复）：文献检索不可用，但知识树（概念结构）可用 →
            # 把 ✗缺口/◇争议 节点转成可生成假设的概念性缺口，而不是直接放弃。
            prompt = (f"当前文献检索服务暂不可用，文献列表为空。请仅基于以下知识树（概念结构，"
                      f"✗缺口=检索暂不可用/缺文献，◇争议=文献多但无定论）分析 2-4 个研究缺口，"
                      f"重点是标注为 ✗缺口 或 ◇争议 的节点对应的待验证问题。\n\n知识树：\n{kt_text}\n\n"
                      "只输出分析结果本身，不要客套话。")
            reply = chat(prompt, system=GAP_SYSTEM)
            _safe_print(f"\n[缺口分析·降级] {reply}")
            RUN_LOG.append({"stage": "缺口分析", "text": reply})
            return {"gap": reply, "status": "缺口分析"}
        return {
            "gap": "没有搜到文献，无法分析缺口。",
            "feedback": "文献列表为空。请重新搜索该主题的论文（优先 search_papers，失败可用 search_web），搜索到的论文会自动存入 literature。",
            "status": "完成",
        }

    paper_text = format_papers(papers)              # 使用辅助函数整理论文列表

    kt_text = format_knowledge_tree(state.get("knowledge_tree"))
    fusion = state.get("paper_fusion") or {}
    fusion_text = ""
    if fusion:
        fusion_text = "\n\n用户提供的论文融合框架（共识/矛盾/互补/共同缺口，缺口分析必须优先纳入）：\n" + json.dumps(fusion, ensure_ascii=False, indent=2)
    prompt = (f"以下是当前领域的相关论文：\n{paper_text}\n\n知识树（概念→文献覆盖情况，作为缺口分析的地图）：\n{kt_text}"
              + fusion_text
              + "\n\n请按系统提示词的输出格式分析这些文献中还没解决的问题（研究缺口）。")
    reply = chat(prompt, system=GAP_SYSTEM)         # 换一套系统提示词，让 LLM 干"分析"的活
    _safe_print(f"\n[缺口分析] {reply}")
    RUN_LOG.append({"stage": "缺口分析", "text": reply})
    return {"gap": reply, "status": "缺口分析"}         # 贴两张便签：缺口 + 阶段

HYPOTHESIS_SYSTEM = """你是一个科研助手，负责基于研究缺口提出可检验的研究假设，并在评审意见的引导下对假设做定向修改。
你的产出会进入评审环节；评审从「可检验性 / 依据扎实度 / 方法可行性 / 新颖性」四个维度打分并给出具体修改指令。
你的目标不是一次写完美，而是每一轮都有针对性地变强。

# 假设写作规范（所有轮次通用）

每个假设必须包含五段（缺一不可）：
① 背景依据：对应哪个研究缺口（引用缺口编号或表述）或哪篇给定文献，说明假设从何而来；
② 明确主张：一句可证伪的核心断言，必须包含核心变量及其操作化定义（测量方式/指标），禁止只堆术语；
③ 预期结果：可量化——给出预测方向、效应量或阈值，不写「显著提升」「明显改善」这类空词；
④ 验证方法：数据/样本来源 + 获取方式 + 粒度 + 时间覆盖 + 实验或分析方法 + 对照或基线 + 统计单位 + 样本量/重复次数；
⑤ 判定标准：什么样的数据结果支持假设、什么样的结果否定假设（支持/推翻阈值必须明确）。

其他规则：
- 术语必须操作化：核心变量给出测量方式；禁止只堆术语。
- 五段必须齐全：样本量/重复次数/统计检验方法为必写项，不允许「评审要求时再补」。
- 写 1-3 个假设：少而精优于多而杂；若多个假设共享同一缺口，注明分工。
- 文献里已有明确答案的方向不要写（避免新颖性为 0）。

# 数据源与可观测性（硬要求）

- 每个数据源都写成独立短句，至少说明四项：是否公开、获取路径或数据库名称、数据粒度、时间覆盖。
- 如果只能确认其中一部分，写「未验证：……」，不得把猜测写成已确认事实。
- 所需变量必须能从所述数据粒度直接构造。例如需要机构间连边，就不能只说有机构级汇总表；需要逐日利率，就不能只说有季度数据。
- 数据时间范围必须覆盖全部研究窗口，且不能使用数据发布前尚不存在的版本做回溯。
- 文献标题不是数据源。若数据源只在文献中被转述、无法确认原始获取方式，标为「未验证」。
- 统计单位必须明确为机构、事件、样品、受试者、年份或其他独立主体。重复观测不得当作独立样本；面板、事件序列、生存分析必须说明单位依赖如何处理。

# 统计与数字一致性（硬要求）

- 时间范围、期数、事件数、分组数、总观测数和模型样本数必须能相互折算，并在正文中保持一致。
- 同一指标的「总样本、子样本、纳入分析样本」要分别命名，禁止用同一个「n」表示不同口径。
- 每个预期数字必须标注来源类型：`[文献值]`、`[推导值]`（给出公式或依据）、`[待标定估计]` 或 `[判定阈值]`。
- 没有先验来源时，不得写 `28.6%`、`R²=0.942`、`95% CI [24.1%, 33.1%]` 这类伪精确结果。改用合理量级、范围或明确写「待标定」。
- 支持阈值与推翻阈值之间不能留下未定义的灰区；若有灰区，必须写明该区间如何处理。

# 与原始研究问题对齐（硬要求）

- 假设必须覆盖原始问题要求的直接结果，不能只回答相邻机制。
- 若问题是「能否预测」，至少要有一个假设包含样本外测试、训练/测试划分和预测指标（如 AUC、召回率、校准误差），不能只做同期相关性或回归系数。
- 若问题是「如何提升/降低/优化」，至少要有一个假设包含基线、可执行干预、主要结局指标和干预相对基线的效果判据。
- 若问题是「为什么/机制是什么」，至少要有一个假设把拟测机制与最终结果指标连接起来，不能只停留在中间变量。
- 若同时包含机制和效果，机制假设可以存在，但必须另有假设或验证环节直接检验最终效果。

# 引用使用与归属（硬要求）

- 只能引用给定文献池中的标题原文；不得新增标题、作者、期刊或 DOI。
- 引用时写清楚它支持哪一句主张；不能只把文献标题放在句尾充当装饰。
- 涉及算法、模型、公式、量表、协议或数据库定义时，若原始方法文献在文献池中，应引用原始出处，而不是只用二手应用文献。
- 若原始方法出处不在文献池中，写「原始方法出处未在给定文献池中，需外部核验」，不得暗示已经核验。
- 引号内文字视为逐字引用，必须给页码、章节或段落定位；没有定位就改成转述，不得伪造原句。

# 表达可读性（与五段内容同等重要）

- 使用短句：一句话只表达一个意思；避免把样品、时间点、试剂、软件和统计方法连续塞进一个长句。
- 每段先写对象，再写处理或测量，最后写对照、样本量和判定条件。
- 术语第一次出现时，用括号给一句简短定义；不要重复解释同一个术语。
- 背景依据写清楚来源；新主张明确写「这是本研究提出的待验证主张」。
- 验证方法按「对象、处理、测量、对照、样本量、统计判据」逐项短句。
- 可读性优化不得删除操作化定义、阈值、样本量、统计方法或反例条件。

# 首轮生成（无评审意见时）

严格从研究缺口出发：每条假设的「依据」必须指向缺口；不写缺口没提到的方向。
若缺口分析给了「候选假设方向」，直接在此基础上具体化，不要另起炉灶。

# 定向修改（有评审意见时，严格按此执行）

1. 底稿选择：历史最高分版本（若与上一版不同）优先，否则用上一版。在底稿上做最小定向修改，保留评审没指出问题的部分，禁止整篇重写。
2. 每条修改必须对应评审意见中的具体条目（引用渲染文本的位置或要点编号 #N）。不得添加评审未要求的新内容（禁止自行加码）。
3. 评审意见处理方式：
   - 带「建议」的 → 直接采纳建议；
   - 标注「已达 X 档，无需继续加码」的 → 不要动；
   - 你认为建议不合理 → 不改，并在修改说明里写明理由。
4. 已修复的问题不要改回去；已 resolved 的要点不要主动重开。
5. 优先级：先修得分最低的 active 要点；若评审给出 bottleneck 维度，优先按评审方向提升该维度。
6. 若评审处于数据模式（只让补文献、没评假设）：本轮不要修改假设主体，只按需更新「依据」的文献表述；把力气留给补搜回来的下一轮。
7. 修改后，若假设里出现新的术语/指标/方法，必须一并给出操作化定义（否则评审会判不可检验）。

# 输出格式

- 首轮：从「假设 1」标题开始，只输出假设本身；禁止写“以下严格依据”“我将从缺口中选择”“综上”“是否需要我继续”等前言、总结或结尾提问。
- 不要输出任务完成清单、格式说明、checklist、✅ 或项目符号式“所有假设均满足”总结。
- 修改轮：先输出修改后的完整假设；然后单独一行输出分隔符：
【修改说明】
  然后逐条列出：
  - 已修改：#编号或位置（一句话说明改了什么）
  - 未修改：#编号或位置（理由）
  - 新增：无（若确实需要新增，必须说明对应哪条评审意见）"""


REVIEW_SYSTEM = """你是一位与作者无关的领域评审专家，负责对研究假设给出诚实、稳定、可执行的评审。
你不知道目标分数，也不知道轮数上限——达标判断由流水线负责。你只负责用同一把尺子打分和提意见。

# 评审流程（按顺序执行）

Step 1 逐维核对：按下方各维度的「加分项 / 减分项」逐项核对假设文本与给定文献（内部推理，不输出中间过程）。
Step 2 逐分累计：按加分项逐项累计、减分项逐项扣除，得出 0-100 的整数分。分数精确到 1 分；每一项按满足程度给整数梯度分（不满足 0 / 部分 1/3 / 基本 2/3 / 完全满分），允许 1 分微调。
Step 3 汇总总分：hypothesis_score = round(0.4×testability + 0.3×evidence + 0.2×feasibility + 0.1×novelty)。
Step 4 写理由：每条理由具体到句子/指标/方法；给出直接改法；说明该问题对应的减分点，以及修复后的预期加分点。
Step 5 更新要点清单：对既有要点逐一重新打分（含 resolved）；新增一般不超过 3 条；判定 active/resolved。
Step 6 外行检验：用一句话复述假设的核心主张（outsider_rephrase）。若复述后丢失了变量、方向或量化信息（而非仅丢失专业名词），说明并相应降低 testability。
Step 7 分数-理由自检：低分维度（如低于 70）应有该维度理由；每轮分数变化应能对应到具体加减分点；若分数与理由脱节，优先修正分数。
Step 8 输出严格 JSON。

# 评分总则

- 分数是评审对假设质量的诚实反映，只依据假设文本与给定文献的实质内容。不存在「因为出现了某个词、某类缺口就应压到某个分数」的机械规则——请按加分项/减分项逐分累计。
- 一分一档：每一项按满足程度给整数梯度分，每 1 分都对应明确的语义增量；输出精确到 1 分。
- 可追溯：每轮在 reasons 中给出分数变化的加减分说明（如「上轮 82 → 本轮 86：+2 操作化定义、+1 测量指标、+1 判定标准」）。
- 自然波动：同一假设文本不变时，两轮分数允许 ±1 的评审自然波动，属正常现象。
- 标题级判断：文献只有标题时，涉及支撑强度的结论标注「标题级判断，需摘要核验确认」；标题级无法确认的内容按「未加分」处理，不计为缺失、不扣分。

# 可检验性 Testability（权重 40，满分 100）

加分项（逐项累计，每项按满足程度给整数梯度分）：
1. 可重述清晰度（满分 10）：能重述为包含变量与关系的清晰研究问题 +10；需少量推测 +6；重述困难 +2。
2. 自变量（满分 15）：命名清楚且有操作化/干预定义 +15；命名清楚但无操作化 +8；命名模糊 +3。
3. 因变量（满分 15）：命名清楚且有测量指标 +15；命名清楚但无测量 +8；模糊 +3。
4. 预测方向（满分 15）：方向与适用条件明确（正/负/非线性/调节） +15；方向明确但边界模糊 +9；无方向 +3。
5. 其他核心变量（调节/控制/协变量）操作化（满分 20）：每个变量 0/5/10（命名+操作化 +10；命名无操作化 +5），至多 2 个。
6. 可证伪结果（满分 10）：明确「什么结果推翻假设」+10；有可证伪性但未写反例 +5。
7. 判定标准（满分 15）：阈值/统计判据/成功判据明确 +15；仅笼统判据 +8。

减分项：变量角色混淆每处 -10（至多 -20）。

# 依据扎实度 Evidence（权重 30，满分 100）

加分项：
1. 概念可识别起点 +10。
2. 核心概念/方法支撑（满分 60）：本项只统计「背景性概念/方法」——即假设成立所依赖、领域内已确立的概念/方法（如器件结构、老化协议、表征手段、已知材料体系）。每个给 0/6/12——在给定文献中有标题对应 +12；领域成熟常识可确认 +12；标题级无法确认 +0（不加不扣）；无任何线索 +0（并进入减分判定）。至多计 5 个。注意：假设新提出的机制/效应/组合（如「某离子极化缓冲某现象」）属于主张级缺口，不是本项统计对象，不应在本项记 0，应放到第 5 项外推链条评估。
3. 方向一致性（满分 10）：以支撑文献本身的趋势方向为准——文献趋势与预测一致 +10；部分一致 +5。不要因为文献未直接验证新主张而只给 +5；新主张未被直接验证属正常，由第 5 项处理。
4. 反证检查（满分 10）：无被忽略的已知反证 +10；未核对反证 +0。
5. 主张外推链条（满分 10）：新主张能指出「相对哪条结论/哪个缺口的延伸」+10；外推链条模糊 +5；无外推说明 +0。

减分项：
- 生造术语（用该术语检索不到主流文献）或与领域常识相悖的概念：每处 -15（至多 -30）。
- 主张与给定文献直接冲突：-20。

三态说明（判断依据，不是硬分数）：
① 成熟技术（如绿色溶剂、刮涂、封装、ISOS 协议）：凭领域常识即可判定，不需要出现在给定文献中；给定文献未覆盖 → 该项按 0 加分，不扣分，可填写 search_request 补搜。
② 主张级缺口：背景性概念/方法均有支撑，缺的只是新主张/新组合的直接数据 → 属正常情况，不扣分；外推链条指明来源即可给满分 +10，不应在「核心概念/方法支撑」或「方向一致性」两项上因此扣分；可在假设中标注「开放性假设」，标注与否不影响打分。
③ 概念级质量差：生造/相悖/无来历 → 按上面减分项处理，并在理由中写出「概念 → 判断 → 依据」三项核对证据（依据 = 文献标题 / 领域常识 / 检索不可得）。

evidence 上限与松绑（关键规则——决定 evidence 能否超过 88）：
- 先按知识树核对：假设涉及的核心概念/方法，是否全部落在「✓已覆盖」节点上，且这些节点均无「◇争议」「✗缺口」标记。
- 满足（全覆盖且无争议/缺口）→ 输出 evidence_basis = "covered_all"：主张级缺口的 88 上限自动解除，evidence 按加分项正常累计，可给 89-92（不超过 92）。
- 不满足（任一涉及节点带「◇争议」或「✗缺口」，或概念在知识树中找不到对应节点）→ evidence_basis = "has_gap_or_debate"：evidence 上限 88，禁止给 89-92。
- 每轮必须输出 evidence_basis 字段（"covered_all" / "has_gap_or_debate"），并在 reasons 中给出一句判断依据（例：「概念 X/Y 对应节点 [1][3]，均 ✓已覆盖 且无争议」）。未输出该字段视为未核对知识树。
- 注意：covered_all ≠ 每个概念都有直接文献；主张级缺口（新主张无直接数据）本身仍属正常，不影响 evidence_basis 判定。

# 方法可行性 Feasibility（权重 20，满分 100）
1. 数据/样本来源：来源明确且规模/获取途径清楚 +20；有来源无规模 +10。
2. 实验/分析方法：方法命名且关键步骤/参数明确 +20；仅命名 +10。
3. 对照/基线/消融设计：对照+基线（或消融）齐备 +20；仅对照 +10。
4. 表征/测量条件：仪器、模式、样品准备、采样频率齐备 +20；部分 +10。
5. 样本量/重复/平行样品：有交代且有依据（统计说明） +20；有交代无依据 +10。

# 新颖性 Novelty（权重 10，满分 100）

加分项：
1. 新关系/机制/组合（满分 30）：提出给定文献中未见的新要素，每个 +10（至多 3 个）。
2. 已有框架上的延伸（满分 15）：新对象/条件/场景 +15；仅换数据集 +8。
3. 创新点集中、变量可隔离（满分 25）：创新点集中可单独检验 +15；变量可隔离 +10。
4. 增量定位（满分 30）：能指出「相对哪条文献结论的新在何处」且差异实质 +30；能定位但差异边缘 +15。

减分项：
- 已被给定文献直接回答：-30。
- 仅措辞/表述差异、无实质增量：-25。
- 堆叠 ≥3 个互不相关新要素且无控制/交互设计：-20。

# data_score 文献充分性（独立维度，0-100）

定义：给定文献列表对该假设的覆盖充分度（有没有、够不够、深不深）。只衡量文献，与假设写得是否具体无关。

加分项：
1. 主题相关起点 +15。
2. 背景性核心概念/方法文献对应（满分 60）：本项只统计「背景性概念/方法」——即假设成立所依赖、领域内已确立的概念/方法（如器件结构、老化协议、表征手段、已知材料体系），按覆盖深度给分，每个 0/4/6/7/10——
   · +10：有 2 篇及以上直接相关文献；
   · +7：有 1 篇直接相关文献；
   · +6：领域成熟常识 + 至少 1 篇间接/相邻文献；
   · +4：仅领域成熟常识可确认（无需文献）；
   · +0：标题级无法确认（不加不扣）；确认无任何对应 +0（并进入减分判定）。
   至多计 6 个。注意：假设新提出的机制/效应/组合（主张级缺口）不是本项统计对象，不应在本项记 0，也不进入减分判定。
3. 关键方法/实验设计有文献支撑（满分 10）：有直接文献且关键参数可对照 +10；有同类方法文献 +6；仅部分提及 +3；无 +0。
4. 文献方向与假设一致（满分 5）：以支撑文献的趋势为准——无冲突且趋势支持 +5；部分一致 +2。
5. 主张级支撑奖励（满分 10）：对每条关键新主张/新机制（主张级缺口），都应尝试在文献池中指出至少 1 篇支撑或外推来源文献（标题级即可），每条 +2，至多 5 条；找不到时在 score_trace.data 中记 0（写「未找到支撑」），不得整项跳过不评估；找不到支撑文献属正常，不加分也不扣分。

减分项：背景性核心概念确认无对应每处 -8（至多 -16）；文献与假设明显冲突 -12（主张级缺口不属于「确认无对应」，不适用该减分）。

重扫与升级规则（关键——保证 data_score 随文献池上涨）：
- 每轮必须基于「当前完整文献池」重新核对每一项覆盖深度，不应沿用上轮判断。
- 文献池扩大后：某概念从「标题级未确认」变为有对应 → 该项应从 +0 升到 +7（或更高）；从 1 篇变 2 篇及以上 → +7 升到 +10；上轮扣过「确认无对应」的概念，本轮找到对应 → 取消该项减分（−8 → 0）。
- 上述升级都应逐项体现在 score_trace.data 中，并在 reasons 中说明（如「文献池新增 2 篇，概念X覆盖 1→2 篇，+7→+10」）。
- 标题级相关判定：「直接相关」指标题明显涉及该概念/方法（如「blade coating」「perovskite stability」出现在标题中）；标题存在合理关联即按相关计，存在歧义时按相关计并在 score_trace.data 标注「标题级」；不要把「未看摘要」当作「不相关」。
- 响应性（本轮生效）：当「文献列表自上一轮是否变化」为「是」时，覆盖升级必须在本轮 data_score 与 score_trace.data 中直接体现，禁止滞后到下一轮；reasons 中写明「文献池本轮新增 N 篇 → 概念X +7→+10」。文献池变化轮是数据分理应上涨的轮次，不受下方「稳定性软约束」限制。

计分明细（可追溯）：
- 每轮必须输出 score_trace.data（格式如「15+54+10+5+4−0=88」，逐项对应上面的加分项/减分项）；这是定位「搜索了但数据分不涨」的关键，缺失视为不完整输出。
- 硬自检：data_score 字段必须等于 score_trace.data 的求和结果；不一致视为输出错误。
- 字段回填：先完成 score_trace.data 逐项求和，再把求和结果原样写入 data_score 字段——data_score 字段是明细的汇总，不是独立判断，禁止出现「明细=90、字段=88」这类脱节。
- 独立性：data_score 与四维相互独立——data_score 只由文献池与假设的概念集合决定；不要因为 data_score 高/低而调整四维分数，四维只反映假设文本质量。

补搜请求与分数解耦：
- data_score 只反映覆盖度与支撑深度。需要补充文献时，在 search_request 字段填写 {"needed": true, "keywords": [具体可检索关键词], "reason": "缺哪类文献"}；不因填写 search_request 而升降 data_score。
- 搜索触发与瓶颈绑定：只有 bottleneck 是 evidence 或 data 时，search_request.needed 才应为 true；bottleneck 是 novelty / testability / feasibility 时，needed 应为 false（内容型瓶颈，补搜文献无法解决），reason 写「内容型瓶颈，无需补搜」；data_score < 60 的数据模式轮仍按契约给出补搜关键词。
- reasons/points 文本中建议避免「补搜/补充搜索/补充检索/重新搜索/追加搜索」等词，搜索意图集中在 search_request 字段；若确实写了这类词，会被视为一次搜索请求（触发软搜索），不影响任何分数。
- 数据模式输出契约（唯一与分数挂钩的格式约束）：data_score < 60 时，mode 应输出 "data"，dimensions 与 hypothesis_score 输出 null，理由聚焦缺哪类文献并给出具体补搜关键词（此时关键词写在文本即可，search_request 可空）。（「文献缺口已确认」转档场景除外，见「# 文献缺口已确认转档」章节。）

# 平台期与加码控制

- 分数低于 85 的维度，优先给出「具体修什么能涨分」的说明，并直接对应到加分项（如「补上操作化定义 +8」）；避免重复旧意见。
- 高分维度（如 ≥85）若没有新的实质问题，写明「已达当前质量水平，无需继续加码」，不必堆砌方法论细节。
- 每轮应输出 bottleneck：当前对总分限制最大的维度，即 权重×(100−该维分) 最大者（权重 40/30/20/10）；数据不足时为 "data"（「文献缺口已确认」转档场景不得为 "data"）。
- 平台期声明（条件触发）：当输入中「最近 3 轮假设分完全相同」且本轮与上一轮意见实质重复（points 名称重合度高或理由文本高度相似）时，必须输出 1 条 dimension=bottleneck 的 reason，issue 以「本轮无新意见：」开头，suggestion 三选一明确写出：
  · 无新增修改方向（当前输入下已到顶）——search_request.needed=false；
  · 换研究角度：写明具体角度（如从材料配方转向器件工艺）——needed=false；
  · 需补充搜索：写明具体关键词——needed=true 且 keywords 填全。
  未满足上述重复条件时不得输出平台期声明（避免提前收敛）。

# 文献缺口已确认转档（最高优先级条件模式）

当评审输入中「文献缺口已确认」为「是」时，本模式覆盖下方所有规则（包括格式约束 2 的数据模式契约、数据模式输出契约、补搜触发规则、以及所有「缺文献即减分/即补搜」的判定）。此时流水线已决定：文献池冻结，不再追加检索，只基于现有文献把假设评审到底。

转档行为（全部适用）：

1. 正常评审四维：mode 必须为 "hypothesis"，dimensions 与 hypothesis_score 必填，按四维 rubric 逐分累计。不得输出 mode="data"，不得把 dimensions / hypothesis_score 置 null。
2. data_score：语义临时切换为「当前文献已足够开始评估假设」的覆盖度基线。先按 data_score 细则正常计分——
   · 正常求和 ≥60：按实际值给，不封顶（字段=求和，硬约束 3 不变）；
   · 正常求和 <60：按转档基线调整到 60-65。调整方式：「确认无任何对应」的概念一律按 +0 计、不进入减分判定（取消 −8/处）；「仅领域常识可确认」的概念按 +6 计。调整后的 score_trace.data 求和必须等于 data_score 字段（硬约束 3 不变），并在 reasons 中写一句「转档基线」。
3. evidence：给定文献池未覆盖 ≠ 概念级质量差。转档场景下，知识树带「✗缺口」的节点一律按「缺口已确认」处理：该概念按 +0 不加不扣、不进入任何减分判定；减分仅保留「生造术语 / 与领域常识相悖 / 与给定文献直接冲突」三类。新主张无直接文献 → 主张级缺口 → 按开放性假设处理。evidence_basis 应输出 has_gap_or_debate（知识树全部 ✓ 且无争议的极少数情况除外，按 covered_all 正常规则），即 evidence 上限 88，禁止给 89-92。
4. 修改意见方向（二选一或组合）：① 把假设收窄到现有文献可支撑的局部（指明具体哪一句、怎么收窄）；② 明确标注「开放性假设」并写明外推来源（相对哪条文献标题 / 知识树哪个节点的延伸）。不得再请求补搜。
5. 输出约束：search_request.needed 必须为 false；bottleneck 不得为 "data"，按四维中 权重×(100−该维分) 最大者输出；reasons/points 中避免出现「补搜 / 补充搜索 / 补充检索 / 重新搜索 / 追加搜索」「无文献支撑 / 缺文献 / 文献缺失 / 缺乏文献 / 没有文献 / 无任何文献 / 文献不足 / 概念级缺口 / 缺乏直接文献支撑 / 无直接支撑」等措辞（这些措辞会被视为搜索或缺口信号），涉及覆盖不足一律写「文献未覆盖（缺口已确认，按开放性处理）」。

边界与例外：

- 与响应性规则互斥：转档场景 = 文献池未变轮。若「文献缺口已确认=是」且「文献列表自上一轮是否变化=是」同时出现（补搜预算耗尽但本轮恰好有新增文献），以文献变化规则为准：正常评审，data_score 按实际覆盖度给（可高于 65）。
- 与稳定性软约束衔接：转档切换轮是语义切换例外——data_score 允许从上一轮 <60 一次性跃升到 60-65（这是评审语义从「数据门控」切换为「覆盖度基线」，不是标准漂移，无需视为异常）；切换完成后、文献池仍不变时，各轮 data_score 应保持稳定（±1 内）。
- 与历史一致性（data 特例）衔接：转档后 data_score 的对照基准仍是文献池——文献池未变，data_score 宜保持 60-65 稳定；文献池意外新增（罕见）则按正常规则上涨。

# 硬性规则（内容判断一律柔性；格式约束共 4 条）

- 格式约束 1（硬）：输出必须是合法 JSON，仅输出 JSON 对象本身，不附加解释文字或代码块标记。
- 格式约束 2（硬，输出契约）：data_score < 60 时 mode="data" 且 dimensions/hypothesis_score 为 null（见上；「文献缺口已确认」转档场景除外）。
- 格式约束 3（硬，字段一致性）：data_score 字段必须等于 score_trace.data 的求和结果；不一致视为输出错误，需修正后再输出。字段不是独立判断，是明细的汇总。
- 格式约束 4（硬，评分对象）：假设含【修改说明】分隔符时，只评分隔符之前的内容；修改说明仅作背景参考，不得因此加减分。
- 防幻觉：引用文献应限于给定文献列表（literature 字段）中出现的标题原文；文献未覆盖的信息写「文献未覆盖」，避免编造指标、方法、数据源。
- 分数语义：越高越好；低分 = 该处应改。低分维度（如低于 70）应给出该维度理由。
- 历史一致性：假设确实修复了上轮问题且无新重大问题时，分数通常不应低于上轮；仅措辞变化时，应避免加分；文本完全相同时，两轮分数允许 ±1 自然波动；分差较大（如超过 10）时，应写明假设文本的具体变化并给出加减分说明。某维度文本本轮没有实质修改（revision_notes 未声称且该部分文本与上轮相同）时，该维分数应沿用上轮（允许 ±1 自然波动），并在该维理由中写明「未修改，沿用上轮 N 分」；只有被修改或被评审指出的维度才允许分数变化，且变化必须对应到具体加减分项。
- 历史一致性（data 特例）：上一条的「仅措辞变化应避免加分 / 文本完全相同时允许 ±1」只约束四维（假设质量）；data_score 的对照基准是文献池——文献池扩大是 data_score 上涨的正当理由，即使假设文本未变也应体现上涨；文献池未变时 data_score 宜保持稳定。
- 稳定性（软约束）：同一假设文本 + 同一文献池的两轮评审，data_score 与四维分差均应 ≤3；若两轮输入完全相同而某分差 >3，应在理由中写明依据。文献池变化轮不适用本约束（该轮数据分应随池上涨）。本条是软约束，不构成机械压分。
- 术语：假设中术语首次出现应就地定义，或能在给定文献中出现；评审不认识的术语，先查给定文献是否出现，出现则不应降分；只有「假设未定义且文献中检索不到」时，才按「术语未操作化」处理并相应降低 testability/evidence。
- 要点清单：points 应使用具体问题条目命名（避免用「可检验性」「依据扎实度」等维度名）；对 active/resolved 逐一重新打分，archived 不重打分；resolved 一般需要连续 2 轮 ≥80 且非本轮焦点，跌破 80 应转回 active；archived 若被本轮 reasons 引用（related_point_id 或名称）应转回 active。评审输入含「已归档要点摘要」（仅 id + name，无分数），允许引用。
- 外行检验：复述后丢失变量/方向/量化信息时，相应降低 testability 并说明（对应 Step 6）。

# 输出 JSON Schema（严格遵循）

{"mode":"hypothesis"或"data","hypothesis_score":整数或null,"data_score":整数,"dimensions":{"testability":整数,"evidence":整数,"feasibility":整数,"novelty":整数},"bottleneck":"testability/evidence/feasibility/novelty/data","evidence_basis":"covered_all/has_gap_or_debate","reasons":[{"dimension":"维度","location":"假设第X句：……","issue":"……","suggestion":"改为……","expected_gain":整数,"related_point_id":整数(可选),"literature":"文献标题(可选，应来自给定列表)"}],"points":[{"id":整数,"name":"具体问题条目","score":0-100,"status":"active/resolved/archived","kind":"hypothesis/data"}],"outsider_rephrase":"一句话复述假设的核心主张","search_request":{"needed":布尔,"keywords":[字符串],"reason":"字符串"},"score_trace":{"testability":"10+15+…","evidence":"…","feasibility":"…","novelty":"…","data":"15+54+10+5+4−0=88"}(可选；data 键每轮必填，且 data_score 必须等于其求和)}

要求：reasons 建议至少 2 条（高分轮可用确认性理由）；每轮对既有要点逐一重新打分；每轮在 reasons 中给出分数变化的加减分说明；data_score<60 时按输出契约输出（「文献缺口已确认」转档场景除外）；每轮必须输出 score_trace.data 计分明细，且 data_score = score_trace.data 求和（硬约束 3）。

# 校准样例

样例 1（弱，总分 39）
假设：「人工智能提高了教学效果。」
计分说明：testability = 6(可重述) + 8(自变量命名无操作化) + 7(因变量可识别无测量) + 9(方向有但边界模糊) + 0 + 0 + 0 = 30；evidence = 10(起点) + 24(两个概念×12，若有对应标题) + 0(方向未核对) + 0 + 6(外推弱) = 40；feasibility = 12+8+10+10+10 = 50；novelty = 10+15+10+10 = 45；data = 15(起点) + 30(3 个背景概念×10) + 6(方法同类) + 5(方向一致) + 6(3 条主张有支撑) − 0 = 62（自检：字段=求和 ✓）。

```json
{
  "mode": "hypothesis",
  "hypothesis_score": 39,
  "data_score": 62,
  "dimensions": {"testability": 30, "evidence": 40, "feasibility": 50, "novelty": 45},
  "bottleneck": "testability",
  "reasons": [
    {"dimension": "testability", "location": "全句", "issue": "自变量未定义：「人工智能」指什么系统/干预？", "suggestion": "改为指定具体干预，如「带即时反馈的智能练习系统」", "expected_gain": 7, "related_point_id": 1},
    {"dimension": "testability", "location": "全句", "issue": "因变量「教学效果」无测量方式", "suggestion": "指定观测指标，如期末成绩、答题正确率", "expected_gain": 8, "related_point_id": 3},
    {"dimension": "evidence", "location": "全句", "issue": "主张未对应到给定文献的具体标题", "suggestion": "为「教学效果」与「人工智能干预」各找至少 1 条给定文献支撑，或明确这是新主张并按外推链条说明", "expected_gain": 12, "related_point_id": 2}
  ],
  "points": [
    {"id": 1, "name": "自变量（干预）未定义", "score": 30, "status": "active", "kind": "hypothesis"},
    {"id": 2, "name": "主张无文献对应", "score": 40, "status": "active", "kind": "hypothesis"},
    {"id": 3, "name": "因变量与测量方式缺失", "score": 35, "status": "active", "kind": "hypothesis"}
  ],
  "outsider_rephrase": "用某种AI做教学会更好。——无法复述具体变量与测量。",
  "search_request": {"needed": false, "keywords": [], "reason": ""},
  "score_trace": {"testability": "6+8+7+9+0+0+0=30", "evidence": "10+24+0+0+6=40", "feasibility": "12+8+10+10+10=50", "novelty": "10+15+10+10=45", "data": "15+30+6+5+6−0=62"}
}
```

样例 2（中，总分 73）
假设：「在中学数学课堂中，使用带即时反馈的智能练习系统（观测指标：答题正确率、完成时长、期末成绩）相比传统纸质练习，能显著提高学生期末成绩（预期效应量 d 约 0.3，控制班级基线成绩）。」
计分说明：testability = 10+15+15+15+10+10+7 = 82；evidence = 10+36(3概念×12)+5+0+11 = 62；feasibility = 20+15+20+8+15 = 78；novelty = 10+15+15+18 = 58；data = 15 + 36(4 个背景概念：10+10+10+6) + 6(方法同类) + 5(方向一致) + 6(3 条主张有支撑) − 0 = 68（自检：字段=求和 ✓）。

```json
{
  "mode": "hypothesis",
  "hypothesis_score": 73,
  "data_score": 68,
  "dimensions": {"testability": 82, "evidence": 62, "feasibility": 78, "novelty": 58},
  "bottleneck": "evidence",
  "reasons": [
    {"dimension": "evidence", "location": "因果主张「显著提高期末成绩」", "issue": "该因果主张为主张级缺口：标题级未见同类对照研究，属正常情况；外推链条较弱（未指明相对哪条结论外推）", "suggestion": "在提出依据中写明相对哪条给定文献结论外推；如需对照文献支撑，可在 search_request 中请求检索相关对照研究", "expected_gain": 11, "related_point_id": 1},
    {"dimension": "feasibility", "location": "验证设计", "issue": "未说明样本量与统计方法", "suggestion": "补样本量依据与分析方法（如 ANCOVA/混合模型）", "expected_gain": 8, "related_point_id": 2}
  ],
  "points": [
    {"id": 1, "name": "因果主张外推链条弱", "score": 58, "status": "active", "kind": "hypothesis"},
    {"id": 2, "name": "样本量与统计方案缺失", "score": 66, "status": "active", "kind": "hypothesis"}
  ],
  "outsider_rephrase": "用了即时反馈练习系统的班级比用传统练习的班级期末成绩更高，效应量约0.3。",
  "search_request": {"needed": false, "keywords": [], "reason": ""},
  "score_trace": {"testability": "10+15+15+15+10+10+7=82", "evidence": "10+36+5+0+11=62", "feasibility": "20+15+20+8+15=78", "novelty": "10+15+15+18=58", "data": "15+36+6+5+6−0=68"}
}
```

样例 3（强，总分 90）
假设：「在中学数学课堂中，使用带即时反馈的智能练习系统（观测指标：答题正确率、完成时长、期末成绩）相比传统纸质练习，能显著提高学生期末成绩（预期效应量 d 约 0.3，控制班级基线成绩与教师差异），且该效应在中低基础学生中更强；采用准实验设计 + 双重差分，机制与可行性由文献 [2][5][9] 支撑。」
计分说明：testability = 10+15+15+15+15+10+15 = 95；evidence = 10+60(5概念×12)+10+8+0(调节效应无直接文献，不加不扣) = 88；feasibility = 20+18+20+17+15 = 90；novelty = 15+15+25+25 = 80；data = 15 + 54(6 个背景概念：4×10 + 2×7) + 10(方法有直接文献且参数可对照) + 5(方向一致) + 4(2 条主张有支撑) − 0 = 88（自检：字段=求和 ✓）。

```json
{
  "mode": "hypothesis",
  "hypothesis_score": 90,
  "data_score": 88,
  "dimensions": {"testability": 95, "evidence": 88, "feasibility": 90, "novelty": 80},
  "bottleneck": "novelty",
  "reasons": [
    {"dimension": "novelty", "location": "整体", "issue": "干预本身已有较多文献，增量主要在「中低基础学生更强」的调节效应；该调节为主张级缺口，外推链条需显式化", "suggestion": "把调节效应写成可检验的显式假设（含交互项预测），并对照文献确认该调节未被研究过", "expected_gain": 6, "related_point_id": 1},
    {"dimension": "feasibility", "location": "准实验设计", "issue": "未说明教师差异的测量与匹配方式", "suggestion": "指定教师特征协变量与匹配策略", "expected_gain": 4, "related_point_id": 2}
  ],
  "points": [
    {"id": 1, "name": "调节效应新意需显式化", "score": 80, "status": "active", "kind": "hypothesis"},
    {"id": 2, "name": "教师差异控制细节", "score": 82, "status": "active", "kind": "hypothesis"},
    {"id": 3, "name": "因果主张文献支撑（上轮）", "score": 92, "status": "resolved", "kind": "hypothesis"}
  ],
  "outsider_rephrase": "用即时反馈练习系统且基础较差的学生提升更明显，整体期末成绩提高约0.3个标准差。",
  "search_request": {"needed": false, "keywords": [], "reason": ""},
  "score_trace": {"testability": "10+15+15+15+15+10+15=95", "evidence": "10+60+10+8+0=88", "feasibility": "20+18+20+17+15=90", "novelty": "15+15+25+25=80", "data": "15+54+10+5+4−0=88"}
}
```

样例 4（data 模式，文献不足 → 输出契约 mode="data"）
假设：「双钙钛矿 Cs2AgBiBr6 在湿热+光照耦合老化下 T80 超 1000 小时。」
计分说明：data_score = 15(起点) + 17(2 个背景概念：10+7) + 3(方法仅部分提及) + 2(方向部分一致) + 5(1 条主张有支撑文献) − 8(「耦合老化测试协议」确认无对应) = 34（自检：字段=求和 ✓）。

```json
{
  "mode": "data",
  "hypothesis_score": null,
  "data_score": 34,
  "dimensions": null,
  "bottleneck": "data",
  "reasons": [
    {"dimension": "data", "location": "核心概念", "issue": "「耦合老化测试协议」「Cs2AgBiBr6 湿热老化数据」在给定文献中均无对应条目", "suggestion": "补搜关键词：Cs2AgBiBr6 stability、damp heat perovskite、coupled aging protocol", "expected_gain": 60, "related_point_id": 1}
  ],
  "points": [
    {"id": 1, "name": "核心概念缺文献对应", "score": 30, "status": "active", "kind": "data"}
  ],
  "outsider_rephrase": "",
  "search_request": {"needed": true, "keywords": ["Cs2AgBiBr6 stability", "damp heat perovskite", "coupled aging protocol"], "reason": "核心概念与协议在给定文献中无对应"},
  "score_trace": {"data": "15+17+3+2+5−8=34"}
}
```

样例 5（文献充分，data_score 90——高分档 + 主张级不加不扣 + 与假设分解耦）
假设：「在 ISOS 协议框架下，采用 Cs/MA/FA 三阳离子体系（文献 [1][2]）、Al2O3 界面钝化（文献 [3]）、湿热-光照耦合老化（文献 [4]）与原位质谱表征（文献 [5]）；新主张：FA+ 脱质子反应是耦合老化下的主导降解路径。」（文献池共 8 篇，6 个背景概念均有 ≥2 篇对应文献）
计分说明：data = 15(起点) + 60(6 个背景概念×10，均 ≥2 篇) + 10(方法有直接文献且参数可对照) + 5(方向一致) + 0(新主张未找到支撑文献，不加不扣) − 0 = 90（自检：字段=求和 ✓）。
注意：本样例数据分高只表示文献池覆盖充分；假设分由四维决定（此处 85），两者解耦——不要把高 data 样例锚定为高总分样例。

```json
{
  "mode": "hypothesis",
  "hypothesis_score": 85,
  "data_score": 90,
  "dimensions": {"testability": 88, "evidence": 90, "feasibility": 78, "novelty": 70},
  "bottleneck": "feasibility",
  "reasons": [
    {"dimension": "feasibility", "location": "验证设计", "issue": "未说明样本量与统计判定方法", "suggestion": "补样本量依据与统计检验方案（如加速老化失效数/威布尔分析）", "expected_gain": 10, "related_point_id": 1},
    {"dimension": "evidence", "location": "新主张「FA+ 脱质子主导降解路径」", "issue": "外推链条未显式化：新主张在文献池中无直接对应，属主张级缺口，不加不扣", "suggestion": "在提出依据中写明相对文献 [4][5] 的哪些观测外推", "expected_gain": 10, "related_point_id": 2}
  ],
  "points": [
    {"id": 1, "name": "样本量与统计方案缺失", "score": 70, "status": "active", "kind": "hypothesis"},
    {"id": 2, "name": "新主张外推链条未显式化", "score": 78, "status": "active", "kind": "hypothesis"}
  ],
  "outsider_rephrase": "在标准老化协议下，三阳离子钙钛矿加氧化铝钝化后，主导失效机制是FA脱质子。",
  "search_request": {"needed": false, "keywords": [], "reason": "文献池已充分，无需补搜"},
  "score_trace": {"testability": "10+15+15+15+15+10+8=88", "evidence": "10+60+10+10+0=90", "feasibility": "20+15+20+8+15=78", "novelty": "20+15+20+15=70", "data": "15+60+10+5+0−0=90"}
}
```

样例 6（文献缺口已确认转档，承接样例 4 同一假设的下一轮）
假设：「双钙钛矿 Cs2AgBiBr6 在湿热+光照耦合老化下 T80 超 1000 小时；老化按 ISOS 协议执行，湿热/光照耦合由腔体级联实现；标注为开放性假设，外推来源为文献 [1] 的湿热老化趋势与文献 [2] 的光照老化协议。」
输入标记：文献缺口已确认=是（连续补搜无新增相关文献）；文献列表自上一轮是否变化=否。
计分说明：testability = 10+15+15+15+10+10+8 = 83；evidence = 10+36(3 个背景概念×12：Cs2AgBiBr6、湿热老化、光照老化)+5+0+10(标注开放性且外推来源明确) = 61；「耦合老化协议」文献池未覆盖 → +0 不加不扣、不进入减分判定（缺口已确认，非概念级质量差）；feasibility = 20+10+10+10+10 = 60；novelty = 10+15+10+18 = 53；data = 15(起点)+38(6 个背景概念：7+7+6+6+6+6)+6(ISOS 协议方法有文献)+2(方向部分一致)+0(主张未找到支撑，不加不扣)−0 = 61（转档基线：常规求和 <60，按「无对应不计减分 + 仅常识概念按 +6」调整至 61；自检：字段=求和 ✓）。
注意：data_score 从上一轮 34 跃升到 61 属转档切换轮的语义切换例外，不是漂移；本轮之后文献池未变则保持 61±1。

```json
{
  "mode": "hypothesis",
  "hypothesis_score": 69,
  "data_score": 61,
  "dimensions": {"testability": 83, "evidence": 61, "feasibility": 60, "novelty": 53},
  "bottleneck": "evidence",
  "evidence_basis": "has_gap_or_debate",
  "reasons": [
    {"dimension": "evidence", "location": "假设第3句（耦合老化协议）", "issue": "该协议在当前文献池中未找到直接对应条目；文献缺口已确认，按开放性处理，不加不扣，不再请求检索", "suggestion": "在假设中明确标注「开放性假设」，写明外推来源：相对文献[1]湿热老化趋势与文献[2]光照老化协议的延伸", "expected_gain": 8, "related_point_id": 1, "literature": "（文献池未覆盖）"},
    {"dimension": "feasibility", "location": "验证设计", "issue": "腔体级联的温湿度范围、光照强度与耦合时序未给出", "suggestion": "按 ISOS 协议补齐关键参数并给出设备规格", "expected_gain": 10, "related_point_id": 2}
  ],
  "points": [
    {"id": 1, "name": "耦合老化协议文献未覆盖（按开放性处理）", "score": 70, "status": "active", "kind": "evidence"},
    {"id": 2, "name": "腔体级联参数缺失", "score": 60, "status": "active", "kind": "hypothesis"}
  ],
  "outsider_rephrase": "双钙钛矿器件在湿热加光照的耦合老化下，寿命T80能超过1000小时。",
  "search_request": {"needed": false, "keywords": [], "reason": "缺口已确认，按开放性假设继续"},
  "score_trace": {"testability": "10+15+15+15+10+10+8=83", "evidence": "10+36+5+0+10=61", "feasibility": "20+10+10+10+10=60", "novelty": "10+15+10+18=53", "data": "15+38+6+2+0−0=61"}
}
```
"""
REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "mode": {"type": "string"},
        "hypothesis_score": {"type": ["integer", "null"]},
        "data_score": {"type": "integer"},
        "dimensions": {
            "type": ["object", "null"],
            "properties": {
                "testability": {"type": "integer"},
                "evidence": {"type": "integer"},
                "feasibility": {"type": "integer"},
                "novelty": {"type": "integer"},
            },
            "required": ["testability", "evidence", "feasibility", "novelty"],
        },
        "bottleneck": {"type": "string"},
        "evidence_basis": {"type": ["string", "null"]},
        "reasons": {"type": "array", "items": {"type": "object"}},
        "points": {"type": "array", "items": {"type": "object"}},
        "outsider_rephrase": {"type": "string"},
        "search_request": {
            "type": ["object", "null"],
            "properties": {
                "needed": {"type": "boolean"},
                "keywords": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
            },
            "required": ["needed", "keywords"],
        },
        "score_trace": {
            "type": ["object", "null"],
            "properties": {
                "testability": {"type": "string"},
                "evidence": {"type": "string"},
                "feasibility": {"type": "string"},
                "novelty": {"type": "string"},
            },
        },
    },
    "required": ["mode", "hypothesis_score", "data_score", "dimensions", "bottleneck", "reasons", "points", "outsider_rephrase"],
}


SEARCH_SIGNAL_PATTERNS = ["补搜", "补充搜索", "补充检索", "补搜索", "重新搜索", "追加搜索"]
SEARCH_DONE_MARKERS = ["已补搜", "经补搜", "补搜后", "已补充搜索"]   # 报告「已经搜过」，不是触发信号
CONCEPT_GAP_PATTERNS = [
    "无文献支撑", "缺文献", "文献缺失", "缺乏文献", "没有文献",
    "无任何文献", "文献不足", "概念级缺口", "缺乏直接文献支撑", "无直接支撑",
]
OPEN_CLAIM_TERMS = ["开放性", "新主张", "新假设", "主张级"]
EXEMPT_TERMS = ["属正常", "不扣分", "不因此扣分", "正常现象"]   # 豁免必须同时出现 OPEN + EXEMPT


def detect_data_insufficient(data):
    """P7：检测「可能需要补搜/存在新概念」信号，返回 (triggered, reason, kind)
    - kind="search_signal"：评审写了「补搜」类建议 → 提示可能存在新概念/需搜索新关键词（仅记录，不压分）；
    - kind="concept_gap"：概念级缺口措辞命中，且无「开放性+正常」豁免语境 → 同样仅记录提示，不压分。
    """
    texts = []
    for r in (data or {}).get("reasons") or []:
        if isinstance(r, dict):
            dim = str(r.get("dimension") or "").strip().lower()
            if dim in ("evidence", "data", "依据", "依据扎实度", "数据", "文献"):
                texts.append(f"{r.get('issue') or ''} {r.get('suggestion') or ''} {r.get('location') or ''}")
    for p in (data or {}).get("points") or []:
        if isinstance(p, dict):
            kind = str(p.get("kind") or "").strip().lower()
            if kind in ("data", "数据"):
                texts.append(f"{p.get('name') or ''}")
    if not texts:
        return False, "", ""
    for t in texts:
        if any(k in t for k in SEARCH_SIGNAL_PATTERNS):
            # v1.1：过去时报告（如「经补搜已确认…」）≠ 要求再搜，不触发；带未来动作指令才算
            done_only = any(k in t for k in SEARCH_DONE_MARKERS) and not any(
                k in t for k in ("建议", "需", "应", "请", "继续", "再补", "关键词"))
            if not done_only:
                return True, t[:60], "search_signal"
        hit = any(k in t for k in CONCEPT_GAP_PATTERNS)
        if hit:
            # P0-2 fix: 只有「核心概念/方法」语境才算概念级缺口；纯主张级缺口（新主张无直接文献）正常，不触发补搜
            concept_scope = any(k in t for k in ("核心概念", "核心方法", "概念级缺口", "概念级"))
            claim_only = any(k in t for k in OPEN_CLAIM_TERMS) and not concept_scope
            if claim_only:
                continue
            has_open = any(k in t for k in OPEN_CLAIM_TERMS)
            has_exempt = any(k in t for k in EXEMPT_TERMS)
            if not (has_open and has_exempt):
                return True, t[:60], "concept_gap"
    return False, "", ""


def render_reasons(reasons):
    """把评审的结构化 reasons 渲染成生成器能读的文本（R4 配套）；已是文本则原样返回"""
    if not isinstance(reasons, list):
        return str(reasons) if reasons else ""
    blocks = []
    for r in reasons:
        if not isinstance(r, dict):
            blocks.append(str(r))
            continue
        dim = r.get("dimension") or "未知维度"
        loc = r.get("location") or ""
        issue = r.get("issue") or ""
        sug = r.get("suggestion") or ""
        gain = r.get("expected_gain")
        gain_txt = f"（预计 +{int(gain)}）" if isinstance(gain, (int, float)) else ""
        lit = r.get("literature") or ""
        lit_txt = f" 文献：{lit}" if lit else ""
        blocks.append(f"【{dim}·{loc}】问题：{issue} → 建议：{sug}{gain_txt}{lit_txt}")
    return "\n".join(blocks)


def split_hypothesis_and_notes(reply):
    """拆分（假设正文, revision_notes），兼容「【修改说明】」与「修改说明：」两种分隔（P0 修复）"""
    m = re.search(r"【修改说明】|修改说明[:：]", reply or "")
    if not m:
        hypothesis = (reply or "").strip()
        notes = ""
    else:
        hypothesis = reply[:m.start()].strip()
        notes = re.sub(r"^【修改说明】|^修改说明[:：]\s*", "", reply[m.start():], count=1).strip()
    first = re.search(r"(?m)^\s*#{0,6}\s*\*{0,2}假设\s*\d+", hypothesis)
    if first:
        hypothesis = hypothesis[first.start():].strip()
    return hypothesis, notes


def floor_for(target):
    """分档达标地板：70→55 / 80→65 / 90→75 / 92→80"""
    return {70: 55, 80: 65, 90: 75, 92: 80}.get(target, 55)


def novelty_floor_for(target):
    """90/92 档额外的新颖性门槛"""
    return {90: 50, 92: 70}.get(target, 0)


def pass_check(state):
    """达标判定 = 分数 + 分档地板 + 90/92 档 novelty 门槛（Diff 3-⑦）"""
    if state.get("anchor_blocked"):
        return False
    target = state.get("quality_target", 80)
    if state.get("data_score", 0) < 60:
        return False
    if state.get("hypothesis_score", 0) < target:
        return False
    dims = state.get("dimensions")
    if not isinstance(dims, dict):
        return False
    vals = [dims.get(k) for k in ("testability", "evidence", "feasibility", "novelty")]
    if not all(isinstance(v, int) for v in vals):
        return False
    if min(vals) < floor_for(target):
        return False
    if dims.get("novelty", 0) < novelty_floor_for(target):
        return False
    return True


MAX_ROUNDS = 10        # 评审循环安全阀（最大轮数）
CONVERGE_PATIENCE = 3  # 连续多少轮没刷新历史最高分就提前收工
MAX_DATA_ROUNDS = 3    # 全局补搜轮数上限（P7 总搜索预算）
MAX_SOFT_SEARCH = 2    # 软搜索独立上限（P9：同一缺口最多软搜 2 次）
def gap_confirmed(state):
    """文献缺口已确认：连续补搜无新文献（cdr>=2）或全局补搜预算耗尽（total>=MAX_DATA_ROUNDS）。"""
    return (state.get("consecutive_data_rounds", 0) >= 2 or
            state.get("total_data_rounds", 0) >= MAX_DATA_ROUNDS)


def exploratory_check(state):
    """假设本身达标但证据覆盖不足时，允许形成明确的探索性方案。

    这个状态不是“验证通过”。它只说明：检索预算已经耗尽或缺口已经确认，
    继续补搜不会改善证据覆盖，因此可以保留一个边界清楚的探索性方案。
    """
    if state.get("anchor_blocked"):
        return False
    if state.get("data_score", 0) >= 60:
        return False
    if state.get("hypothesis_score", 0) < state.get("quality_target", 80):
        return False

    dims = state.get("dimensions")
    if not isinstance(dims, dict):
        return False
    vals = [dims.get(k) for k in ("testability", "evidence", "feasibility", "novelty")]
    if not all(isinstance(v, int) for v in vals):
        return False
    target = state.get("quality_target", 80)
    if min(vals) < floor_for(target):
        return False
    if dims.get("novelty", 0) < novelty_floor_for(target):
        return False

    evidence_resolved = bool(
        state.get("gap_confirmed_latched", False)
        or state.get("p10_forced", False)
        or state.get("search_exhausted", False)
        or state.get("consecutive_data_rounds", 0) >= 2
        or state.get("total_data_rounds", 0) >= MAX_DATA_ROUNDS
    )
    return evidence_resolved


def assess_plan_release(state, passed=None):
    """返回 (plan_status, evidence_status, release_reason)。

    validated：证据覆盖与假设质量都达到放行门槛。
    exploratory：假设质量达到门槛，但证据覆盖不足，必须明确标注为探索性。
    in_progress：仍需要补搜或修改假设。
    """
    if state.get("anchor_blocked"):
        return (
            "in_progress",
            "searching",
            "存在未经核验的图表/补充材料定位或既成实验事实，必须先修正并重新评审。",
        )
    validated = pass_check(state) if passed is None else bool(passed)
    if validated:
        return (
            "validated",
            "verified",
            "假设质量与原始证据覆盖均达到门槛，可进入验证方案。",
        )
    if exploratory_check(state):
        return (
            "exploratory",
            "insufficient_evidence",
            "检索预算已耗尽或文献缺口已确认；假设可检验但证据覆盖不足，只能作为探索性方案，不能标记为验证通过。",
        )
    return (
        "in_progress",
        "searching",
        "假设质量或证据覆盖尚未达到门槛，需继续补搜或修改假设。",
    )


MAX_TOTAL_SEARCH = 4   # 软+硬共用全局搜索上限（含 data 模式轮）
RECENT_REVIEWS = 3     # 假设生成时携带最近几轮评审意见

# ============ L5-L7 辅助（批次 C/D，2026-08-10）============

def _hash12(text):
    """L5/N6：正文/文献/缺口快照的 12 位短哈希。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def _body_for_hash(hypothesis):
    """N6：body_hash 在剥离【修改说明】后的正文上算。"""
    h = str(hypothesis or "")
    for sep in ("【修改说明】", "修改说明："):
        if sep in h:
            h = h.split(sep)[0].strip()
            break
    return h


def _append_review_jsonl(state, row):
    """L5：评审轮/探测轮各 append 一行到 运行文件夹/03_评审JSONL.jsonl。"""
    folder = state.get("run_folder")
    if not folder:
        return
    try:
        path = os.path.join(folder, "03_评审JSONL.jsonl")
        with io.open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as exc:
        RUN_LOG.append({"stage": "评审JSONL", "note": f"落盘失败：{exc}"})


_NEGATIVE_WORDS = ("仍", "缺", "未", "低", "不足", "缺失", "没", "重新出现")


def _point_reactivated(point, reasons):
    """L3 复活判定（N2）：reasons 里 related_point_id 指向该点 且 issue 含负面语义，
    或某条 reason 的 issue 与该点名称相似度 > 0.8。"""
    if not isinstance(reasons, list):
        return False
    name = str(point.get("name") or "")
    for r in reasons:
        if not isinstance(r, dict):
            continue
        rid = r.get("related_point_id")
        issue = str(r.get("issue") or "")
        if rid == point.get("id"):
            if any(w in issue for w in _NEGATIVE_WORDS):
                return True
        elif rid is None and name and difflib.SequenceMatcher(None, name, issue).ratio() > 0.8:
            return True
    return False


def _name_in_texts(name, texts):
    """要点名称是否出现在任一评审文本里（归档前「最近 2 轮未被引用」判定）。"""
    for t in texts:
        if t and name in t:
            return True
    return False


def _paper_relevant_query(query, title):
    """L6（N5）：搜索词 term 级相关判定——无关文献不进池。
    - 中文：任意 >=2 字连续子串命中标题 -> 相关；
    - 英文：>=4 字符 term 至少 2 个不同 term 命中标题 -> 相关（1 个 term 命中也算）；
    - 无法判定（query/标题缺失或 term 不足）-> 放行（宁宽勿误杀）。"""
    query = str(query or "").strip()
    title = str(title or "").lower()
    if not query or not title:
        return True
    cjk = re.findall(r"[\u4e00-\u9fff]+", query)
    if cjk:
        # 中文 query：至少一个 >=2 字连续子串命中标题才算相关（避免「锂电池 寿命预测」误放行）
        return any(len(seg) >= 2 and seg.lower() in title for seg in cjk)
    terms = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) >= 4]
    terms = list(dict.fromkeys(terms))
    if len(terms) >= 2:
        return sum(1 for t in terms if t in title) >= 2
    if len(terms) == 1:
        return terms[0] in title
    return True


def _tree_rebuild_needed(new_relevant, pool_size):
    """L7（N4）：相关新增 >=3 且 >= 池的 50% 才触发重拆（双条件防池小时过激）。"""
    return new_relevant >= 3 and pool_size > 0 and new_relevant * 2 >= pool_size


def _health_check_archived(prompt, archived_points):
    """L3 健康复查（N2）：每 3 轮对全部 archived 要点一次性重打分。
    结果只进 JSONL 不进生成器 prompt；跌破 88 由调用方转 active。
    返回 {point_id: score}；调用失败返回空 dict。"""
    if not archived_points:
        return {}
    sys_p = ("你是一名科研评审专家。下面给出当前假设与若干已归档要点。"
             "请逐点判断该要点对应的问题在当前假设中是否仍然成立：问题已彻底解决给 90 分以上，"
             "问题重新出现或局部回归给 88 分以下。只输出 JSON：{\"<要点id>\": 0-100 的整数}。")
    user_p = (prompt + "\n\n已归档要点（只判断当前状态，不重新打分）：\n"
              + "\n".join(f"- {p['id']}. {p['name']}" for p in archived_points))
    try:
        data = json_chat(user_p, system=sys_p, schema={"type": "object"}, max_retries=1)
    except JsonChatError:
        return {}
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                out[int(k)] = int(v)
            except (TypeError, ValueError):
                continue
    return out


def merge_points(existing, new_points, round_no, reasons=None, reasons_text="", prev_reasons_text="", bottleneck=""):
    """把评审输出的要点合并进清单：已存在按 id 追加历史，新要点分配新 id。要点只增不减。
    v0.2：历史追加 status；resolved 跌破 80 -> 强制转 active。
    L3：archived 被 reasons 引用 -> 复活；连续 2 轮 >=88、最近 2 轮未被引用、非瓶颈焦点 -> 归档。"""
    by_id = {}
    for p in existing:
        if p.get("id") is not None:
            by_id[p["id"]] = p
    max_id = max(by_id, default=0)
    if isinstance(new_points, list):
        for np in new_points:
            pid = np.get("id")
            name = str(np.get("name") or "未命名要点")
            try:
                score = int(np.get("score"))
            except (TypeError, ValueError):
                continue
            status = np.get("status")
            if status not in ("active", "resolved", "archived"):
                status = "active"
            if pid is not None and pid in by_id:
                prev_status = by_id[pid]["history"][-1].get("status", "active")
                if prev_status == "resolved" and score < 80:
                    status = "active"
                if prev_status == "archived" and _point_reactivated(by_id[pid], reasons):
                    status = "active"          # L3 复活
                by_id[pid]["history"].append({"round": round_no, "score": score, "status": status})
            else:
                max_id += 1
                by_id[max_id] = {"id": max_id, "name": name,
                                 "history": [{"round": round_no, "score": score, "status": status}]}
    # L3 归档：连续 2 轮 >=88、最近 2 轮未被引用、非瓶颈焦点 -> archived
    for p in by_id.values():
        hist = p["history"]
        last = hist[-1]
        if last.get("status") not in ("active", "resolved"):
            continue
        if len(hist) < 2 or last.get("score", 0) < 88 or hist[-2].get("score", 0) < 88:
            continue
        name = str(p.get("name") or "")
        if not name:
            continue
        if _point_reactivated(p, reasons):
            continue                              # L3：本轮被引用（复活/提及）不归档
        if bottleneck and name in bottleneck:
            continue
        _reason_issues = [str(r.get("issue") or "") for r in (reasons or []) if isinstance(r, dict)]
        if _name_in_texts(name, [reasons_text, prev_reasons_text] + _reason_issues):
            continue
        last["status"] = "archived"
    return sorted(by_id.values(), key=lambda p: p["id"])


def _resolve_data_trace(data, data_score):
    """解析 score_trace.data 算式；与 data_score 字段不一致时返回 (修正分, True)。"""
    try:
        st = (data or {}).get("score_trace") or {}
        expr = str(st.get("data") or "") if isinstance(st, dict) else ""
        if expr and "=" in expr:
            lhs = expr.split("=")[0].strip()
            lhs = lhs.replace("−", "-").replace("－", "-").replace(" ", "")
            nums = [int(x) for x in re.findall(r"[+-]?\d+", lhs)]
            if nums:
                trace_sum = sum(nums)
                if 0 <= trace_sum <= 100 and abs(trace_sum - data_score) >= 1:
                    return trace_sum, True
    except Exception:
        pass
    return data_score, False

def _load_human_feedback(question):
    """按题目读取预置人工反馈（约定目录 LOG_DIR/feedback/<question_hash>/feedback.json）。"""
    try:
        import hashlib
        _fb_dir = os.path.join(LOG_DIR, "feedback", hashlib.md5(str(question).encode("utf-8")).hexdigest()[:8])
        _fb = human_loop.load_feedback(_fb_dir)
        return _fb
    except Exception:
        return None


def _load_run_feedback(state):
    """读取本运行的人工反馈：优先运行目录 run_folder/feedback.json（网页追问落盘），
    找不到再回退预置目录 LOG_DIR/feedback/<hash>/feedback.json。"""
    run_folder = state.get("run_folder")
    if run_folder:
        try:
            _fb = human_loop.load_feedback(run_folder)
            if _fb:
                return _fb
        except Exception:
            pass
    return _load_human_feedback(state.get("question"))


def _adjudicate_feedback(state):
    """消费时甄别：读取反馈 -> 去重（last_feedback_ts）-> 甄别 -> 缓存进 state。

    返回 (adj, fb, created_at)：
      adj         甄别结果 dict（verdict/rationale/accepted_questions/rejected_reasons/error）
      fb          原始人工反馈 dict（可能为 None）
      created_at  反馈时间戳/内容指纹（去重键；无反馈时为空串）
    已消费过的反馈直接读缓存 state["adj_cache"]，不重复调用甄别器（省 token、避免每轮重复注入）。
    """
    fb = _load_run_feedback(state)
    if not fb or fb.get("verdict") == "未评价":
        return None, None, ""
    created_at = str(fb.get("created_at") or "")
    if not created_at:
        try:
            created_at = "h" + hashlib.md5(
                json.dumps(fb, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        except Exception:
            created_at = "h0"
    cached = state.get("adj_cache")
    if created_at and state.get("last_feedback_ts") == created_at and cached:
        return cached, fb, created_at
    parts = []
    for i, q in enumerate(fb.get("questions") or [], 1):
        parts.append(f"疑问{i}：{q}")
    for i, s in enumerate(fb.get("suggestions") or [], 1):
        parts.append(f"建议{i}：{s}")
    if fb.get("score_opinion"):
        parts.append(f"分数意见：{fb['score_opinion']}")
    user_text = "\n".join(parts).strip()
    if not user_text:
        return None, fb, created_at
    hypothesis = state.get("best_hypothesis") or state.get("hypothesis") or ""
    try:
        adj = adjudicate(state.get("question"), hypothesis, user_text)
    except Exception as exc:
        adj = {"verdict": "无法判断", "rationale": "甄别异常：%s" % exc,
               "accepted_questions": [], "rejected_reasons": [], "error": str(exc)}
    state["adj_cache"] = adj
    state["last_feedback_ts"] = created_at
    try:
        _safe_print("\n[质疑甄别] verdict=%s 采纳=%d 拒绝=%d" % (
            adj.get("verdict"), len(adj.get("accepted_questions") or []),
            len(adj.get("rejected_reasons") or [])))
        RUN_LOG.append({"stage": "质疑甄别", "round": len(state.get("review") or []) + 1,
                        "text": adj.get("rationale", "")})
    except Exception:
        pass
    return adj, fb, created_at


def _format_adj_for_review(adj, fb):
    """评审侧注入文本：
      - 合理/部分合理：注入被采纳的改写后疑问（评审必须逐条回应）；
      - 不合理：不注入（甄别已否决，避免毒建议干扰评审）；
      - 无法判断/甄别失败：注入原始质疑，请评审独立裁决。
    返回注入文本或 None（不注入）。"""
    if not adj:
        return None
    verdict = adj.get("verdict")
    if verdict in ("合理", "部分合理"):
        qs = [a.get("rewritten") or a.get("original") for a in adj.get("accepted_questions") or []]
        qs = [q for q in qs if q]
        if not qs:
            return None
        return human_loop.format_feedback_for_review(
            {"verdict": "质疑", "questions": qs, "suggestions": []})
    if verdict == "不合理":
        return None
    lines = ["【用户质疑（甄别未能判定，请评审独立裁决是否影响假设）】"]
    if fb:
        for i, q in enumerate(fb.get("questions") or [], 1):
            lines.append(f"{i}. {q}")
        for i, s in enumerate(fb.get("suggestions") or [], 1):
            lines.append(f"{i}. {s}")
    if adj.get("rationale"):
        lines.append(f"甄别说明：{adj['rationale']}")
    return "\n".join(lines)


def _format_adj_for_generator(adj):
    """生成器侧注入文本：只注入被采纳内容（合理/部分合理）；其余一律不注入（保守）。"""
    if not adj or adj.get("verdict") not in ("合理", "部分合理"):
        return None
    qs = [a.get("rewritten") or a.get("original") for a in adj.get("accepted_questions") or []]
    qs = [q for q in qs if q]
    if not qs:
        return None
    return human_loop.format_feedback_for_generator(
        {"verdict": "修改", "questions": [], "suggestions": qs})


def review_hypothesis(state):
    _write_progress(state, "评审", f"第 {state['rounds'] + 1} 轮评审中…", round_no=state["rounds"] + 1)
    _t0_review = time.time()          # L5：本轮评审耗时
    _run_no = state.get("run_no")
    # ===== 人在回路：读取预置人工反馈 / 网页追问（甄别后注入）=====
    _adj, _fb, _created = _adjudicate_feedback(state)
    _adj_review = _format_adj_for_review(_adj, _fb)
    human_feedback_text = _adj_review if _adj_review else "（无人工反馈）"

    # ===== consumer_test：下游 AI 消费测试（上轮数据不足则跳过，沿用上次报告）=====
    consumer_status, consumer_questions, consumer_assumptions = "consumable", [], []
    if state.get("hypothesis") and state.get("data_score", 0) >= 60:
        try:
            consumer_status, consumer_questions, consumer_assumptions = consumer.consumer_test(state["hypothesis"])
        except Exception:
            consumer_status, consumer_questions, consumer_assumptions = "needs_clarification", ["（消费测试异常，保守判需澄清）"], []
    consumer_report = consumer.format_consumer_report(consumer_status, consumer_questions, consumer_assumptions)

    # ===== 组装 user prompt（Diff 2：只放输入上下文，规则全在 system prompt）=====
    kt_text = format_knowledge_tree(state.get("knowledge_tree"))
    history_text = "（暂无历史）"
    if state.get("score_history"):
        history_text = "\n".join(
            f"第 {h['round']} 轮：假设分 {h['hypothesis_score']}，数据分 {h['data_score']}"
            for h in state["score_history"]
        )

    prev_reviews = state.get("review", [])[-RECENT_REVIEWS:]
    if prev_reviews:
        prev_review_text = "\n\n".join(f"【第 {i + 1} 轮】\n{t}" for i, t in enumerate(prev_reviews))
    else:
        prev_review_text = "（暂无）"

    points_text = "（暂无）"
    if state.get("points"):
        plines = []
        for p in state["points"]:
            last = p["history"][-1]
            st = last.get("status", "active")
            plines.append(f"{p['id']}. {p['name']} —— 最近（第 {last['round']} 轮）{last['score']} 分，状态 {st}")
        points_text = "\n".join(plines)

    previous_hypothesis = state["hypothesis_history"][-1] if state.get("hypothesis_history") else "（无，这是首轮评审）"
    revision_notes = state.get("revision_notes") or "（无）"
    # v0.10 N7：评审只评假设正文；【修改说明】及之后内容仅作背景参考（双保险，生成器侧已剥离）
    hyp_for_review = state["hypothesis"]
    for _sep in ("【修改说明】", "修改说明："):
        if _sep in hyp_for_review:
            hyp_for_review = hyp_for_review.split(_sep)[0].strip()
    anchor_issues = anchor_checker.check_hypothesis(hyp_for_review, state)
    anchor_blocked = bool(anchor_issues)
    anchor_report = anchor_checker.format_review_report(anchor_issues)
    archived_text = ""
    _archived = [p for p in state.get("points", []) if p.get("history") and p["history"][-1].get("status") == "archived"]
    if _archived:
        archived_text = "已归档要点（id+名称，不重打分）：" + "；".join(f"{p['id']}. {p['name']}" for p in _archived)
    tree_mark = state.get("knowledge_tree_mark") or ""

    prev_hash = state.get("prev_literature_hash", "")
    cur_hash = json.dumps(state.get("literature", []), ensure_ascii=False, sort_keys=True)
    literature_changed = "否" if (prev_hash and prev_hash == cur_hash) else "是"

    prompt = f"""原始问题：{state['question']}

研究缺口：{state['gap']}

待评审的研究假设（只评这部分，【修改说明】不参与打分）：
{hyp_for_review}

上一版假设（用于判断本轮是否真正改进，而非只改措辞）：
{previous_hypothesis}

生成器声称的修改（revision_notes，可能为空）：
{revision_notes}

相关文献（仅标题/期刊/年份）：
{format_papers(state['literature'])}

知识树（概念→文献覆盖，供核对「依据」维；✗缺口=缺文献，◇争议=文献无定论；◇争议 节点上的主张不算缺依据）：
{kt_text}

文献列表自上一轮是否变化：{literature_changed}（是/否）

{tree_mark}

文献缺口已确认：{('是' if gap_confirmed(state) else '否')}（连续补搜无新增相关文献，或全局补搜预算已耗尽；为「是」时，请按系统提示词「# 文献缺口已确认转档」规则评审：不要输出数据模式，不要请求补搜）

历史分数轨迹（请保持同一把尺子，不要标准漂移）：
{history_text}

最近 {RECENT_REVIEWS} 轮评审意见：
{prev_review_text}

要点清单（历轮累计、只增不减，含历史分与状态）：
{points_text}

{archived_text}

人工反馈（优先级最高，必须逐条回应；无则写（无人工反馈））：
{human_feedback_text}

下游 AI 消费测试报告（独立消费者只收到假设文本；追问清单中的每一项都必须在本轮评审意见中给出解决方向）：
{consumer_report}

确定性锚点核查（代码给出，属于硬门，必须逐条处理）：
{anchor_report}

请按系统提示词中的「评审流程」完成评审，仅输出 JSON。"""

    # ===== 调用：json_chat（JSON mode + schema 校验 + 自纠错重试），失败走兜底链 =====
    data = None
    raw = None
    degraded = ""
    try:
        data = json_chat(prompt, system=REVIEW_SYSTEM, schema=REVIEW_SCHEMA, max_retries=1)
    except JsonChatError as e:
        raw = e.last_content
        degraded = "json_chat 失败，进入兜底链"
        data = extract_json(raw) if raw else None

    mode = (data or {}).get("mode", "hypothesis")
    data_score = 0
    data_corrected = False
    try:
        data_score = int((data or {}).get("data_score") or 0)
    except (TypeError, ValueError):
        data_score = 0
    # v0.8: score_trace.data 算式与 data_score 字段不一致时，用算式结果强制覆盖（同假设分加权和强制）
    data_score, data_corrected = _resolve_data_trace(data, data_score)
    if data_corrected:
        degraded = (degraded or "") + " data计分修正(score_trace)"
    bottleneck = (data or {}).get("bottleneck") or ""
    evidence_basis = None      # evidence 松绑：covered_all / has_gap_or_debate / None(未声明或数据模式)
    outsider = (data or {}).get("outsider_rephrase") or ""

    dims = (data or {}).get("dimensions")
    if isinstance(dims, dict) and all(k in dims for k in ("testability", "evidence", "feasibility", "novelty")):
        try:
            dims = {k: int(dims[k]) for k in ("testability", "evidence", "feasibility", "novelty")}
        except (TypeError, ValueError):
            dims = None
    else:
        dims = None

    reasons = None
    reasons_raw = (data or {}).get("reasons")
    if isinstance(reasons_raw, list) and reasons_raw and all(isinstance(r, dict) for r in reasons_raw):
        reasons = reasons_raw
    elif isinstance(reasons_raw, list):
        reasons = "\n".join(str(r) for r in reasons_raw)
    elif isinstance(reasons_raw, str):
        reasons = reasons_raw

    data_mode = (mode == "data") or (data_score < 60)

    # P10 缺口已确认 -> 转开放假设评审（不再无限 data 模式空转）。
    # 关键约束：缺口确认不是证据补充，因此绝不修改原始 data_score。
    # 2026-08-29 加固：转档状态粘滞（gap_confirmed_latched）——一旦文献缺口确认，
    # 后续轮文献池未变就持续按转档评审，防止评审再输出 data<60 时回到数据模式造成 61↔15 震荡。
    _gap_latched = bool(state.get("gap_confirmed_latched", False))
    p10_forced_this_round = False
    if data_mode and (_gap_latched or gap_confirmed(state)) and state.get("rounds", 0) > 0:
        data_mode = False
        mode = "hypothesis"
        p10_forced_this_round = True
        degraded = (degraded or "") + " 缺口已确认转探索性评审(不抬分)"

    # P7 补搜提示（不压分）：补搜信号/概念级缺口 -> 仅记录提示（供日志），分数保留评审原值
    data_forced = False
    data_forced_reason = ""
    data_forced_kind = ""
    if not data_mode:
        forced, why, data_forced_kind = detect_data_insufficient(data)
        if forced:
            data_forced = True
            data_forced_reason = f"[{data_forced_kind}] {why}"

    # P9 软搜索：评审 search_request 结构化字段（优先）+ 词法兜底 -> 写 search_requested / search_keywords（不动分数）
    search_requested = False
    search_keywords = []
    sr = (data or {}).get("search_request") if isinstance(data, dict) else None
    if isinstance(sr, dict) and sr.get("needed"):
        kw = sr.get("keywords")
        if isinstance(kw, list):
            search_keywords = [str(k).strip() for k in kw if str(k).strip()]
        elif isinstance(kw, str) and kw.strip():
            search_keywords = [kw.strip()]
        if search_keywords:
            search_requested = True
    if not search_requested and data_forced and not data_mode:
        search_requested = True                       # 词法兜底：文本命中补搜/概念级缺口
        search_keywords = [data_forced_reason]

    # P6-3/L6 搜索循环上限：cdr 语义 =「相关新增=0」（N5：无关文献进 filtered_out 不算新增）
    prev_cdr = state.get("consecutive_data_rounds", 0)
    if state.get("last_new_relevant", 0) > 0:
        consecutive_data_rounds = 0
    elif data_mode:
        consecutive_data_rounds = prev_cdr + 1
    else:
        consecutive_data_rounds = 0
    _tv = state.get("tree_version", 0)   # L7：收敛/平台期窗口只在同一 tree_version 内比较

    # P7 总搜索预算：数据模式每轮 +1（全局上限 MAX_DATA_ROUNDS）
    total_data_rounds = state.get("total_data_rounds", 0) + (1 if data_mode else 0)

    if data_mode:
        dims = None

    score_corrected = False
    if data_mode:
        # P0-1 fix: 数据模式保留评审真实假设分；v0.5 契约 data 模式 hypothesis_score=null 时沿用上轮分
        raw_hs = (data or {}).get("hypothesis_score")
        if raw_hs is None or raw_hs == "":
            hypothesis_score = state.get("hypothesis_score", 0)
        else:
            try:
                hypothesis_score = int(raw_hs)
            except (TypeError, ValueError):
                hypothesis_score = state.get("hypothesis_score", 0)
        if not reasons:
            reasons = "评审判定数据/文献不足，请结合原始问题重新评估文献覆盖。"
    else:
        hypothesis_score = 0
        try:
            hypothesis_score = int((data or {}).get("hypothesis_score") or 0)
        except (TypeError, ValueError):
            hypothesis_score = 0

        if not dims:
            # 兜底链第 3 档：dimensions 也没解析出来 -> 用上轮分，强制补搜一轮
            degraded = degraded or "dimensions 解析失败"
            hypothesis_score = state.get("hypothesis_score", 0)
            data_score = min(data_score, 55)
            data_mode = True
            if not reasons:
                reasons = "评审输出无法解析，强制补搜/重生成一轮。"
        else:
            # evidence 松绑：评审声明 evidence_basis + 代码兜底（报 covered_all 但知识树有争议/缺口 -> 强制 has_gap_or_debate 封顶 88）
            declared_basis = None
            if isinstance((data or {}).get("evidence_basis"), str):
                declared_basis = data["evidence_basis"].strip()
            dims["evidence"], evidence_basis, evidence_capped, ev_reason = apply_evidence_basis(
                dims, declared_basis, state.get("knowledge_tree"), state.get("hypothesis", "")
            )
            if evidence_capped:
                degraded = (degraded or "") + " evidence封顶(" + ("covered_all被否决" if declared_basis == "covered_all" else "争议/缺口") + ")"
            compute = round(0.4 * dims["testability"] + 0.3 * dims["evidence"] + 0.2 * dims["feasibility"] + 0.1 * dims["novelty"])
            if hypothesis_score != compute:
                # 加权和校验失败：回喂一次重试；仍不符就用 compute 覆盖（evidence_capped 是代码封顶导致的必然差异，不回喂）
                if not evidence_capped:
                    try:
                        retry = json_chat(
                            prompt + "\n\n注意：你上次的 hypothesis_score 与四维加权和（40/30/20/10）不一致，请重新计算并修正。",
                            system=REVIEW_SYSTEM, schema=REVIEW_SCHEMA, max_retries=0,
                        )
                        r_dims = (retry or {}).get("dimensions")
                        r_score = (retry or {}).get("hypothesis_score")
                        if isinstance(r_dims, dict) and all(k in r_dims for k in ("testability", "evidence", "feasibility", "novelty")):
                            r_compute = round(0.4 * int(r_dims["testability"]) + 0.3 * int(r_dims["evidence"]) + 0.2 * int(r_dims["feasibility"]) + 0.1 * int(r_dims["novelty"]))
                            if abs(int(r_score or 0) - r_compute) <= 2:
                                dims = {k: int(r_dims[k]) for k in ("testability", "evidence", "feasibility", "novelty")}
                                hypothesis_score = int(r_score or 0)
                                data_score = int((retry or {}).get("data_score") or data_score)
                                data_score, d_corr2 = _resolve_data_trace(retry, data_score)
                                if d_corr2:
                                    data_corrected = True
                                    degraded = (degraded or "") + " data计分修正(score_trace)"
                                bottleneck = (retry or {}).get("bottleneck") or bottleneck
                                r_reasons = (retry or {}).get("reasons")
                                if isinstance(r_reasons, list) and r_reasons and all(isinstance(x, dict) for x in r_reasons):
                                    reasons = r_reasons
                    except JsonChatError:
                        pass
                if hypothesis_score != compute:
                    hypothesis_score = compute
                    score_corrected = True
                    degraded = degraded or "加权和修正"

    # ===== 消费门（批次2-2A 修订 20260810）：不再封顶分数，只作反馈与日志 =====
    # 下游 AI 追问清单已通过 consumer_report 进评审 prompt，评审必须逐条给出解决方向；
    # 自包含性属「可检验性」维度职责，由评审意见约束。强制 min(分,80) 与 90 档目标冲突
    #（目标 90 + 封顶 80 = 永远无法达标；实测 3 组在线回归全部卡 80，故取消压分）。
    self_gated = False
    if not data_mode and consumer_status == "needs_clarification":
        self_gated = True
        degraded = (degraded or "") + " 消费需澄清(不压分)"
    if state.get("quality_target", 90) >= 92 and consumer_assumptions:
        hypothesis_score = min(hypothesis_score, 92)
        self_gated = True
        degraded = (degraded or "") + " 92档assumptions非空封顶92"

    if not reasons:
        reasons = "评审未给出可解析的理由。"
    if anchor_blocked:
        anchor_reason = anchor_checker.build_review_reason(anchor_issues)
        if isinstance(reasons, list):
            reasons.append(anchor_reason)
        else:
            reasons = str(reasons) + "\n" + render_reasons([anchor_reason])
    if isinstance(reasons, list):
        reasons_text = render_reasons(reasons)
    else:
        reasons_text = str(reasons)

    # ===== points 状态机（代码侧强制，Diff 3-⑥）=====
    new_points_raw = (data or {}).get("points") if isinstance((data or {}).get("points"), list) else []
    _prev_review_text = state.get("review", [])[-1] if state.get("review") else ""
    points = merge_points(state.get("points", []), new_points_raw, state["rounds"] + 1,
                          reasons=reasons if isinstance(reasons, list) else None,
                          reasons_text=reasons_text,
                          prev_reasons_text=_prev_review_text,
                          bottleneck=bottleneck)

    data_ok = data_score >= 60
    # 本轮缺口已确认（与 route_review 判定一致：cdr 或总预算用本轮计算值）
    gap_confirmed_this_round = (consecutive_data_rounds >= 2 or total_data_rounds >= MAX_DATA_ROUNDS)

    # ===== L4 分歧探测（N1）：同一轮输入快照重评一次；每 run <=2 次；失败记 probe_failed 不并入统计 =====
    divergence = None
    probe_failed = False
    _prev_hs = state.get("hypothesis_score", 0)
    _delta = hypothesis_score - _prev_hs
    _prev_rev_raw = state.get("review", [])[-1] if state.get("review") else ""
    _rev_sim = difflib.SequenceMatcher(None, _prev_rev_raw, reasons_text).ratio() if (_prev_rev_raw and reasons_text) else 0.0
    _json_fallback = bool(degraded and ("score_trace" in degraded or "json_fallback" in degraded
                                        or "json_chat 失败" in degraded or "兜底链" in degraded))
    _probe_trigger = (score_corrected or data_corrected or _json_fallback or abs(_delta) > 10
                      or (_rev_sim > 0.95 and abs(_delta) >= 5))
    if _probe_trigger and state.get("probe_count", 0) < 2:
        try:
            probe = json_chat(prompt, system=REVIEW_SYSTEM, schema=REVIEW_SCHEMA, max_retries=1)
            pd = (probe or {}).get("dimensions")
            ps = None
            try:
                ps = int((probe or {}).get("hypothesis_score") or 0)
            except (TypeError, ValueError):
                ps = None
            if isinstance(pd, dict) and all(k in pd for k in ("testability", "evidence", "feasibility", "novelty")):
                try:
                    pd = {k: int(pd[k]) for k in ("testability", "evidence", "feasibility", "novelty")}
                except (TypeError, ValueError):
                    pd = None
            if pd is None:
                probe_failed = True
            else:
                if ps is None:
                    ps = round(0.4 * pd["testability"] + 0.3 * pd["evidence"] + 0.2 * pd["feasibility"] + 0.1 * pd["novelty"])
                _trig = ("corrected" if (score_corrected or data_corrected) else
                         "json_fallback" if _json_fallback else
                         "big_delta" if abs(_delta) > 10 else "noop_high_sim")
                divergence = {"probe_hypothesis_score": ps, "probe_dimensions": pd,
                              "delta": ps - hypothesis_score, "trigger": _trig}
        except JsonChatError:
            probe_failed = True

    # ===== L3 健康复查（N2）：每 3 轮对 archived 要点一次性重打分；跌破 88 自动转 active =====
    _hc_round = state.get("points_healthcheck_round", 0)
    healthcheck = None
    if state["rounds"] + 1 % 3 == 0:
        _archived_pts = [p for p in points
                         if p.get("history") and p["history"][-1].get("status") == "archived"]
        if _archived_pts and (state["rounds"] + 1 - _hc_round) >= 3:
            _hc = _health_check_archived(prompt, _archived_pts)
            if _hc:
                healthcheck = _hc
                _hc_round = state["rounds"] + 1
                for _p in points:
                    if (_p.get("id") in _hc and _hc[_p["id"]] < 88 and _p.get("history")
                            and _p["history"][-1].get("status") == "archived"):
                        _p["history"][-1]["status"] = "active"   # 健康复查：跌破 88 复活

    snapshot = {
        "quality_target": state["quality_target"],
        "data_score": data_score,
        "hypothesis_score": hypothesis_score,
        "dimensions": dims,
        "gap_confirmed_latched": _gap_latched,
        "p10_forced": p10_forced_this_round,
        "search_exhausted": bool(state.get("search_exhausted")),
        "consecutive_data_rounds": consecutive_data_rounds,
        "total_data_rounds": total_data_rounds,
        "anchor_blocked": anchor_blocked,
    }
    passed = pass_check(snapshot)
    if p10_forced_this_round:
        passed = False   # P10 转档轮：缺口刚确认，不允许直接标记为证据已验证
    plan_status, evidence_status, release_reason = assess_plan_release(snapshot, passed=passed)
    search_exhausted = bool(state.get("search_exhausted"))
    if anchor_blocked:
        feedback = "确定性锚点核查未通过：" + anchor_report
    elif passed or plan_status == "exploratory":
        feedback = ""
    elif data_ok and gap_confirmed_this_round:
        feedback = "文献缺口已确认（多次补充搜索无新增相关文献）。请把假设收窄到现有文献可支撑的局部，或在『依据』中明确标注该主张为开放性假设；不得再次请求补搜。"
    elif not data_ok:
        if gap_confirmed_this_round:
            feedback = "文献缺口已确认（连续补搜无新增相关文献）。请把假设收窄到现有文献可支撑的局部，或在『依据』中明确标注该主张为开放性假设；不要再次要求补搜。"
        else:
            feedback = f"评审认为文献/数据不足。评审意见原文：\n{reasons_text}\n请按其中的补搜关键词重新搜索。"
    elif search_exhausted:
        feedback = "文献缺口已确认（多次补充搜索无新增相关文献）。请把假设收窄到现有文献可支撑的局部，或明确标注为开放性假设；不得再次请求补搜。"
    elif search_requested:
        kw_text = "、".join(search_keywords) if search_keywords else "相关关键词"
        feedback = f"评审建议补充文献（关键词：{kw_text}）。请用 search_papers 搜索这些关键词，将新文献存入 literature，然后输出 Final Answer。"
    else:
        feedback = ""

    score_history = state.get("score_history", []) + [
        {"round": state["rounds"] + 1, "hypothesis_score": hypothesis_score, "data_score": data_score,
         "score_corrected": score_corrected, "data_corrected": data_corrected, "self_gated": self_gated,
         "passed": passed, "plan_status": plan_status,
         "tree_version": _tv}
    ]

    # ===== v0.10 L2：平台期声明检测 + 双闸先验 =====
    platform_declared = False
    platform_suggestion = ""
    if isinstance(reasons, list) and reasons and all(isinstance(r, dict) for r in reasons):
        for r in reasons:
            iss = str(r.get("issue", "") or "")
            if iss.startswith("本轮无新意见："):
                platform_declared = True
                platform_suggestion = str(r.get("suggestion", "") or "")
                break
    _recent_scores = [h.get("hypothesis_score") for h in score_history[-3:]
                      if h.get("data_score", 0) >= 60 and h.get("tree_version", 0) == _tv]
    _scores_same = len(_recent_scores) >= 3 and len(set(_recent_scores)) == 1
    _prev_names = {str(p.get("name", "")) for p in state.get("points", []) if p.get("name")}
    _cur_names = {str(p.get("name", "")) for p in points if p.get("name")}
    _union = _prev_names | _cur_names
    _jacc = (len(_prev_names & _cur_names) / len(_union)) if _union else 0.0
    _prev_rev = state.get("review", [])[-1] if state.get("review") else ""
    _sim = difflib.SequenceMatcher(None, _prev_rev, reasons_text).ratio() if (_prev_rev and reasons_text) else 0.0
    platform_gate = _scores_same and (_jacc > 0.6 or _sim > 0.7)
    platform_active = platform_declared and platform_gate

    best_hypothesis = state.get("best_hypothesis", "")
    best_score = state.get("best_score", 0)
    best_data_score = state.get("best_data_score", 0)
    # 2026-08-29 修复：数据模式轮的假设分不参与 best 竞争（其文献不足、评分不可靠），
    # 避免 best 绑定在 data<60 轮导致 best_data_score 出现 15 等误导值。
    if (not data_mode) and (not anchor_blocked) and hypothesis_score > best_score:
        best_hypothesis = state["hypothesis"]
        best_score = hypothesis_score
        best_data_score = data_score

    RUN_LOG.append({
        "stage": "评审",
        "round": state["rounds"] + 1,
        "hypothesis_score": hypothesis_score,
        "data_score": data_score,
        "passed": passed,
        "plan_status": plan_status,
        "evidence_status": evidence_status,
        "release_reason": release_reason,
        "data_mode": data_mode,
        "dimensions": copy.deepcopy(dims),
        "bottleneck": bottleneck,
        "evidence_basis": evidence_basis,
        "outsider_rephrase": outsider,
        "score_corrected": score_corrected,
        "data_corrected": data_corrected,
        "degraded": degraded,
        "data_forced": data_forced,
        "data_forced_kind": data_forced_kind,
        "data_forced_reason": data_forced_reason,
        "self_gated": self_gated,
        "search_requested": search_requested,
        "search_keywords": search_keywords,
        "soft_search_rounds": state.get("soft_search_rounds", 0),
        "total_soft_searches": state.get("total_soft_searches", 0),
        "search_exhausted": search_exhausted,
        "total_data_rounds": total_data_rounds,
        "points": copy.deepcopy(points),
        "text": json.dumps(data, ensure_ascii=False, indent=2) if data else raw,
    })

    if anchor_blocked:
        new_reviews = state["review"] + [reasons_text]
    elif data_ok:
        new_reviews = state["review"] + [reasons_text]
        if search_exhausted:
            new_reviews = new_reviews + [feedback]   # 软搜耗尽 -> 收窄指令必须给生成器
    elif consecutive_data_rounds >= 2:
        new_reviews = state["review"] + [feedback]   # 文献缺口已确认 -> 生成器必须看到
    else:
        new_reviews = state["review"]

    # 转档粘滞更新：本轮转档过 -> 保持 latched；文献池有相关新增 -> 解除（重新评估覆盖）
    _new_latched = bool(_gap_latched or p10_forced_this_round)
    if state.get("last_new_relevant", 0) > 0:
        _new_latched = False

    result = {
        "review": new_reviews,
        "hypothesis_score": hypothesis_score,
        "data_score": data_score,
        "rounds": state["rounds"] + 1,
        "status": "探索性完成" if plan_status == "exploratory" else ("完成" if passed else "评审"),
        "feedback": feedback,
        "score_history": score_history,
        "best_hypothesis": best_hypothesis,
        "best_score": best_score,
        "best_data_score": best_data_score,
        "plan_status": plan_status,
        "evidence_status": evidence_status,
        "release_reason": release_reason,
        "anchor_blocked": anchor_blocked,
        "anchor_issues": copy.deepcopy(anchor_issues),
        "gap_confirmed_latched": _new_latched,
        "points": points,
        "dimensions": dims,
        "bottleneck": bottleneck,
        "prev_literature_hash": cur_hash,
        "literature_changed": literature_changed == "是",
        "consecutive_data_rounds": consecutive_data_rounds,
        "total_data_rounds": total_data_rounds,
        "search_requested": search_requested,
        "search_keywords": search_keywords,
        "soft_search_rounds": state.get("soft_search_rounds", 0),
        "total_soft_searches": state.get("total_soft_searches", 0),
        "search_exhausted": search_exhausted,
        "p10_forced": p10_forced_this_round,
        "self_gated": self_gated,
        "platform_declared": platform_declared,
        "platform_suggestion": platform_suggestion,
        "platform_active": platform_active,
        "tree_version": _tv,
        "probe_count": state.get("probe_count", 0) + (1 if divergence is not None else 0),
        "points_healthcheck_round": _hc_round,
        "last_new_relevant": state.get("last_new_relevant", 0),
        "filtered_out": state.get("filtered_out", []),
        "knowledge_tree_mark": "",          # N4：评审已消费重拆标记（只注入重拆后第一轮）
    }

    # ===== L5：评审 JSONL 落盘（每轮一行；探测结果附在 divergence，健康复查附在 healthcheck）=====
    _corrected_list = []
    if score_corrected:
        _corrected_list.append("hypothesis_score")
    if data_corrected:
        _corrected_list.append("data_score")
    if self_gated:
        _corrected_list.append("self_gated")
    if not _corrected_list:
        _corrected_list = ["none"]
    _body = _body_for_hash(state.get("hypothesis"))
    _lit_titles = sorted({(p.get("标题") or p.get("title") or "") for p in state.get("literature", [])})
    _jsonl_row = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "run_no": _run_no,
        "backend": os.getenv("LLM_BACKEND", "deepseek"),
        "model": llm_client.active_model(),
        "temperature": 0,
        "round": state["rounds"] + 1,
        "mode": mode,
        "hypothesis_score": hypothesis_score,
        "data_score": data_score,
        "dimensions": copy.deepcopy(dims),
        "bottleneck": bottleneck,
        "evidence_basis": evidence_basis,
        "corrected": _corrected_list,
        "input": {
            "body_hash": _hash12(_body),
            "body_len": len(_body),
            "literature_hash": _hash12("\n".join(_lit_titles)),
            "literature_count": len(state.get("literature") or []),
            "gap_hash": _hash12(state.get("gap") or ""),
        },
        "output": {
            "reasons": (reasons if isinstance(reasons, list) else [])[:6],
            "points": copy.deepcopy(points),
            "search_request": (data or {}).get("search_request"),
            "score_trace": (data or {}).get("score_trace"),
        },
        "perf": {"duration_s": round(time.time() - _t0_review, 2), "tokens": None, "attempts": None},
        "divergence": divergence,
        "probe_failed": probe_failed,
        "tree_version": _tv,
        "healthcheck": healthcheck,
        "last_feedback_ts": state.get("last_feedback_ts", 0),
        "adj_cache": state.get("adj_cache"),
    }
    _jp = get_last_json_perf()
    if _jp:
        _jsonl_row["perf"].update(_jp)
    _append_review_jsonl(state, _jsonl_row)

    if data_mode:
        result["data_review"] = state.get("data_review", []) + [reasons_text]

    print(f"\n[评审] 模式={mode} 假设分={hypothesis_score} 数据分={data_score} 加权修正={score_corrected} 降级={degraded or '无'}")
    try:
        print(json.dumps(data, ensure_ascii=False, indent=2) if data else f"(原文)\n{raw}")
    except UnicodeEncodeError:
        print(json.dumps(data, ensure_ascii=True, indent=2) if data else f"(原文)\n{raw}")
    _write_progress(state, "评审",
                    f"假设分 {hypothesis_score} / 数据分 {data_score}" + (f"，瓶颈：{bottleneck}" if bottleneck else ""),
                    round_no=state["rounds"] + 1)
    return result


def build_revision_prompt(state, gap_text, paper_text, adj=None):
    """修改轮提示词：每轮用「填充」方式更新上下文（轮次/分数变化/瓶颈/上轮声称的修改），
    并对「改差」「原地打转」「文献缺失」给出针对性指令。"""
    # 人在回路（生成器侧）：甄别后只注入被采纳内容（合理/部分合理），其余一律不注入
    _adj_gen = _format_adj_for_generator(adj)
    human_gen_text = _adj_gen if _adj_gen else "（无人工反馈）"
    kt_text = format_knowledge_tree(state.get("knowledge_tree"))
    current = state["hypothesis"]
    best = state.get("best_hypothesis", "")
    if best and state.get("best_score", 0) > state.get("hypothesis_score", 0):
        base = best        # 上一版改差了，退回到历史最高分版本继续改
    else:
        base = current

    # 最近 RECENT_REVIEWS 轮评审意见（带分数）
    hist = state.get("score_history", [])
    total = len(state["review"])
    blocks = []
    for j in range(max(0, total - RECENT_REVIEWS), total):
        k = j + 1
        score_part = ""
        if k - 1 < len(hist):
            h = hist[k - 1]
            score_part = f"（假设分 {h['hypothesis_score']}，数据分 {h['data_score']}）"
        blocks.append(f"【第 {k} 轮评审 {score_part}】\n{state['review'][j]}")
    review_text = "\n\n".join(blocks)

    data_notes = state.get("data_review", [])
    if data_notes:
        extra = "\n\n".join(f"【数据不足轮次的补搜建议】\n{t}" for t in data_notes)
        review_text = review_text + ("\n\n" if review_text else "") + extra

    # 分数轨迹：跳过数据模式轮（假设分是沿用值，会误导生成器）
    valid = [h for h in hist if h.get("data_score", 0) >= 60]
    traj = " → ".join(str(h["hypothesis_score"]) for h in valid) or "（暂无）"

    last_score = valid[-1]["hypothesis_score"] if valid else None
    prev_score = valid[-2]["hypothesis_score"] if len(valid) >= 2 else None

    # 连续停滞检测（有效评审轮内，从末尾数连续相同分数）
    plateau = 0
    if last_score is not None:
        for h in reversed(valid):
            if h["hypothesis_score"] == last_score:
                plateau += 1
            else:
                break

    bottleneck = state.get("bottleneck") or ""
    revision_notes = state.get("revision_notes") or "（无）"
    tree_mark_gen = state.get("knowledge_tree_mark") or ""   # N4：重拆后生成器也得知晓分数跳变是重估"

    # 累计评审要点（带状态，标出本轮优先目标）
    points_summary = "（暂无）"
    if state.get("points"):
        plines = []
        for p in state["points"]:
            last = p["history"][-1]
            st = last.get("status", "active")
            tag = ""
            if st == "active" and last["score"] < 80:
                tag = " ← 本轮优先目标"
            elif st == "resolved":
                tag = "（已解决，勿重开）"
            plines.append(f"{p['id']}. {p['name']}（最近 {last['score']} 分，{st}）{tag}")
        points_summary = "\n".join(plines)

    prompt = f"""研究缺口：
{gap_text}

相关文献：
{paper_text}

知识树（概念→文献覆盖底图；✗缺口=缺文献，◇争议=文献无定论；两者都是假设生长点）：
{kt_text}

{tree_mark_gen}

上一版假设（本次评审的对象）：
{current}

"""
    if base != current:
        prompt += f"""历史最高分版本（比上一版好，作为修改底稿）：
{base}

"""
    prompt += f"""最近评审意见：
{review_text}

分数轨迹（数据不足轮次已省略）：
{traj}

上一轮你声称的修改（revision_notes，供核对是否真的改了）：
{revision_notes}

评审本轮指出的瓶颈维度：{bottleneck or "（未给出）"}

评审要点（历轮累计；active 且低分 = 本轮优先目标）：
{points_summary}

人工反馈（修改假设时优先满足；无法满足须在修改说明里写明原因）：
{human_gen_text}

"""
    guide = []
    if prev_score is not None and last_score < prev_score:
        guide.append(f"警告：上一轮分数从 {prev_score} 降到 {last_score}，说明上一轮改坏了。必须退回历史最高分版本（{state.get('best_score', 0)} 分）作为底稿，只修复评审指出的问题，不要引入新内容。")
    if plateau >= 3:
        guide.append(f"注意：分数已连续 {plateau} 轮停在 {last_score} 没有提升，说明你在原地打转。本轮只做一件事：盯住瓶颈维度「{bottleneck or '评审意见里分数最低的维度'}」，把它提升到下一档；其他维度一律不动，不要重复旧修改方向。")
    elif bottleneck:
        guide.append(f"优先把瓶颈维度「{bottleneck}」提升到下一档（对照评审意见里该维度的具体建议）。")
    guide.append("若评审指出的是「文献/依据缺失」类问题：不要编造文献标题，写明『文献未覆盖，需补搜』，其余问题按意见修改。")
    guide.append("若评审注明「文献缺口已确认」：只收窄假设或标注开放性假设，不得再次要求补搜。")
    guide.append("修改完成后，在末尾单独输出「修改说明：」段落：列出本次改动的评审要点编号（如 #3、#5），并注明哪些评审意见选择不改及原因；禁止添加评审未要求的新内容。")
    guide_text = "\n".join(guide)

    prompt += f"""修改要求：
1. 以底稿为基础做【定向修改】：本轮只改瓶颈维度（或评审明确指出问题）对应的句子/段落，其余内容原样保留，禁止整篇重写、禁止为改而改；
2. 每条修改必须对应评审意见里的具体条目或要点编号（#N），不得添加评审未要求的新内容（禁止自行加码）；
3. 评审标注「已达 X 档，无需继续加码」的地方不要动；
4. 已修复的问题不要改回去；已 resolved 的要点不要主动重开；
5. 优先提升 active 且得分低的要点；
6. 直接采纳评审理由中给出的具体修改指令（评审说改哪句/补什么指标，就照做）；
{guide_text}"""
    return prompt



def hypothesis_gen(state):
    _write_progress(state, "假设生成",
                    f"第 {len(state.get('review') or []) + 1} 轮生成/修改假设",
                    round_no=len(state.get('review') or []) + 1)
    gap_text = state["gap"]
    paper_text = format_papers(state["literature"])
    kt_text = format_knowledge_tree(state.get("knowledge_tree"))

    # 文献检索失败降级（2026-08-29 稳定性修复）：不再因「没有搜到文献」直接放弃。
    # 只要知识树（概念结构）可用，就基于领域常识继续生成可检验假设并标注证据级别；
    # 连概念结构都没有时才放弃（极罕见，说明知识整合阶段已崩）。
    no_lit = (not gap_text or "没有搜到文献" in gap_text or not paper_text)
    _tree = state.get("knowledge_tree")
    _kt_ok = bool(isinstance(_tree, dict) and _tree.get("sub_problems"))
    if no_lit and not _kt_ok:
        return {"hypothesis": "没有研究缺口（文献为空），无法提出假设。", "status": "完成"}

    # 质疑甄别：读取/缓存用户反馈（生成器只消费被采纳部分）
    _adj, _fb, _created = _adjudicate_feedback(state)

    if not state["review"]:
        # 第一次生成：从零写
        if no_lit:
            # 降级：文献检索不可用，基于知识树 + 领域常识生成，并明确标注证据级别
            prompt = (f"研究缺口：\n{gap_text}\n\n知识树（概念结构；✗缺口=检索暂不可用/缺文献）：\n{kt_text}\n\n"
                      "当前文献检索服务暂不可用，文献列表为空。请基于上述概念结构和你的领域常识，"
                      "提出 1-2 个可检验的研究假设。要求：明确自变量/因变量/预测方向/判定标准；"
                      "并在假设末尾单独一行注明「文献依据级别：领域常识（检索暂不可用），需实验验证」。")
        else:
            prompt = f"研究缺口：\n{gap_text}\n\n知识树（概念→文献覆盖；✗缺口=缺文献，◇争议=文献多但无定论——◇争议 与 ✗缺口 都是建议优先探索的假设生长点）：\n{kt_text}\n\n相关文献：\n{paper_text}\n\n请按系统提示词的「假设写作规范」提出可检验的研究假设。"
    else:
        # 有评审意见：每轮动态填充上下文做定向修改
        prompt = build_revision_prompt(state, gap_text, paper_text, _adj)

    reply = chat(prompt, system=HYPOTHESIS_SYSTEM)
    _safe_print(f"\n[假设生成] {reply}")
    RUN_LOG.append({"stage": "假设生成", "round": len(state["review"]) + 1, "text": reply})

    # 拆出假设正文与「修改说明」：revision_notes 单独进 state（P3 1.4；P0 修复统一两种分隔）
    hypothesis_part, revision_notes = split_hypothesis_and_notes(reply)

    # 把上一版假设存档进历史，供评审对比“真改进 vs 只改措辞”
    history = state.get("hypothesis_history", [])
    prev = state.get("hypothesis", "")
    if prev and prev != hypothesis_part:
        history = history + [prev]
    return {"hypothesis": hypothesis_part, "hypothesis_history": history, "status": "完成",
            "revision_notes": revision_notes,
            "last_feedback_ts": state.get("last_feedback_ts", 0),
            "adj_cache": state.get("adj_cache")}


def route_review(state):
    # 安全阀优先：锚点未修复时也允许在轮数上限终止，避免无限循环；
    # 但 review 节点已把 plan_status 固定为 in_progress，终态不能标成 validated。
    if state["rounds"] >= MAX_ROUNDS:                    # 安全阀
        return END
    if state.get("anchor_blocked"):
        return "hypothesis"                              # 锚点幻觉未修复，禁止放行
    if pass_check(state):
        return "verify"                                  # 证据与假设均达标 -> 验证方案
    if exploratory_check(state):
        return "verify"                                  # 假设达标但证据不足 -> 生成探索性验证方案
    # ===== 收敛硬停（提前到 data 分支之前，对含数据模式轮在内的全部轮次生效）=====
    # 最近 CONVERGE_PATIENCE 轮假设分与数据分完全相同（无任何进展）-> 直接收工（L7：同 tree_version 内比较）
    _hist_all = [h for h in state.get("score_history", [])
                 if h.get("tree_version", 0) == state.get("tree_version", 0)]
    if len(_hist_all) >= CONVERGE_PATIENCE:
        _tail = _hist_all[-CONVERGE_PATIENCE:]
        if len({(h.get("hypothesis_score"), h.get("data_score")) for h in _tail}) == 1:
            return END
    if state.get("data_score", 0) < 60:
        if state.get("consecutive_data_rounds", 0) >= 2 or state.get("total_data_rounds", 0) >= MAX_DATA_ROUNDS:
            return "hypothesis"                          # 连续无新文献或预算耗尽：收窄/标注开放性，不再烧轮次
        return "llm"                                     # 数据模式：强制补搜，本轮不判达标
    if state.get("p10_forced"):
        return "hypothesis"                              # P10 强制转档轮：不许直接达标，先收窄/标注开放性
    # ===== 收敛判定（强制，先于软搜索：连续无提升必须停，软搜请求不得挡住）=====
    # P1 修复：过滤数据模式轮——其 hypothesis_score 是沿用的旧值，参与判定会造成停滞误判
    # L7（N4）：收敛/平台期窗口只在同一 tree_version 内比较，重拆后参照系重置
    _tv_r = state.get("tree_version", 0)
    history = [h for h in state.get("score_history", [])
               if h.get("data_score", 0) >= 60 and h.get("tree_version", 0) == _tv_r]
    # 硬停（用户要求）：最近连续 CONVERGE_PATIENCE 轮假设分与数据分完全相同 -> 直接收工
    if len(history) >= CONVERGE_PATIENCE + 1:
        tail = history[-CONVERGE_PATIENCE:]
        if len({(h["hypothesis_score"], h["data_score"]) for h in tail}) == 1:
            return END
    # 停滞判定：最近 CONVERGE_PATIENCE 轮没有超过更早之前的最高分（含持平）=> 提前收工
    if len(history) >= CONVERGE_PATIENCE + 1:
        recent = history[-CONVERGE_PATIENCE:]
        before = history[:-CONVERGE_PATIENCE]
        best_before = max((h["hypothesis_score"] for h in before), default=0)
        if max((h["hypothesis_score"] for h in recent)) <= best_before:
            return END
    # ===== v0.10 L2：平台期三段路由（双闸通过才生效；未通过按普通轮继续）=====
    if state.get("platform_active"):
        _sugg = state.get("platform_suggestion", "") or ""
        if state.get("search_requested") or "需补充搜索" in _sugg or "搜索" in _sugg or "检索" in _sugg:
            if state.get("soft_search_rounds", 0) < MAX_SOFT_SEARCH and \
               (state.get("total_soft_searches", 0) + state.get("total_data_rounds", 0)) < MAX_TOTAL_SEARCH:
                return "llm"
            return END
        if "换研究角度" in _sugg or "角度" in _sugg:
            return "hypothesis"
        return END
    # P9 软搜索分支：数据够但评审要补搜 -> 回 llm 真实搜索（收敛判定之后，不再拦截收敛）
    if state.get("search_requested") and not state.get("search_exhausted"):
        if state.get("soft_search_rounds", 0) < MAX_SOFT_SEARCH and \
           (state.get("total_soft_searches", 0) + state.get("total_data_rounds", 0)) < MAX_TOTAL_SEARCH:
            return "llm"
    return "hypothesis"                                  # 数据够但假设不行，带意见改


def format_papers(papers):
    lines = []
    for p in papers:
        title = p.get("标题") or p.get("title") or "无标题"
        journal = p.get("期刊") or p.get("venue") or ""
        year = p.get("年份") or p.get("year") or ""
        if journal or year:
            lines.append(f"- 《{title}》 ({journal}, {year})")
        else:
            lines.append(f"- 《{title}》")
        if p.get("摘要"):
            lines.append(f"   {p['摘要']}")
    return "\n".join(lines)


# ============ 路由：判断下一步去哪 ============
def route(state):
    last = state["history"][-1]
    if state.get("tree_rebuild_pending"):
        return "gap"                 # L7：相关新增达标 -> 先回 knowledge 节点重拆知识树
    if state.get("given_papers") and not state.get("paper_parse_done"):
        return "papers"             # 论文输入模块：先解析用户论文，再进知识整合
    if "final answer" in last.lower():
        return "gap"                 # 原来 return END，现在先去缺口分析
    if state["steps"] >= MAX_STEPS * (state["rounds"] + 1):
        return "gap"                 # 每轮评审多给 MAX_STEPS 次补搜预算，用完去缺口分析
    return "tool"


# ============ 画分数迭代折线图 ============
def plot_scores(score_history, quality_target, out_dir="runs"):
    """把每轮评审的假设分/数据分画成折线图，保存到 runs\\scores_时间戳.png"""
    if not score_history:
        return None

    # 中文字体（跟 extract_capacity.py 同一套设置）
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "SimSun"]
    plt.rcParams["axes.unicode_minus"] = False

    rounds = [s["round"] for s in score_history]
    hyp = [s["hypothesis_score"] for s in score_history]
    dat = [s["data_score"] for s in score_history]
    best_run = []
    m = 0
    for s in score_history:
        m = max(m, s["hypothesis_score"])
        best_run.append(m)

    plt.figure(figsize=(8, 5))
    plt.plot(rounds, hyp, marker="o", label="假设分 hypothesis_score", color="#d62728")
    plt.plot(rounds, dat, marker="s", label="数据分 data_score", color="#1f77b4")
    plt.plot(rounds, best_run, linestyle="--", color="#2ca02c", label="历史最高分（累计）")
    plt.axhline(quality_target, color="gray", linestyle="--", label=f"及格线 {quality_target}")
    plt.ylim(0, 100)
    plt.xlabel("评审轮数 round")
    plt.ylabel("分数")
    plt.title("假设质量迭代曲线")
    plt.legend()
    plt.grid(True, linestyle=":", alpha=0.6)

    os.makedirs(out_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(out_dir, f"scores_{ts}.png")
    try:
        plt.savefig(path, dpi=150, bbox_inches="tight")
    except OSError:
        # Optional chart output must not turn a completed research run into a
        # process failure when the Windows path-length limit is exceeded.
        try:
            path = os.path.join(out_dir, "scores.png")
            plt.savefig(path, dpi=150, bbox_inches="tight")
        except OSError:
            plt.close()
            return None
    plt.close()
    return os.path.abspath(path)


# ============ 把本次运行完整日志写成 Markdown，落到桌面 27日/生成日志 ============
def clean_filename(text, limit=25):
    """去掉文件名非法字符，截断到 limit 个字"""
    text = re.sub(r'[<>:"/\\|?*\n\r\t]', "", text).strip()
    return text[:limit] or "未命名问题"

def next_run_number(log_dir=LOG_DIR):
    """读/写运行序号（第几次），序号文件放在日志目录里"""
    os.makedirs(log_dir, exist_ok=True)
    counter_path = os.path.join(log_dir, "_运行序号.txt")
    n = 0
    try:
        with open(counter_path, "r", encoding="utf-8") as f:
            n = int(f.read().strip() or "0")
    except (IOError, ValueError):
        n = 0
    n += 1
    with open(counter_path, "w", encoding="utf-8") as f:
        f.write(str(n))
    return n


def short_topic(question):
    """从问题里提炼简短主题词，用于文件名（内容简化）"""
    q = question or ""
    if "钙钛矿" in q:
        return "钙钛矿"
    if "锂" in q and ("电池" in q or "寿命" in q):
        return "锂电"
    return clean_filename(q, 6) or "科研"


def group_run_entries(run_log):
    """把 RUN_LOG 按轮次分组，返回 [(round, [entries]), ...]；缺口分析等无轮次内容归 round=0"""
    groups = {}
    order = []
    for e in run_log:
        r = e.get("round", 0)
        if r not in groups:
            groups[r] = []
            order.append(r)
        groups[r].append(e)
    return [(r, groups[r]) for r in order]


def save_run_log(result, question, quality_target):
    """日志落盘（v2 文件夹模式）：每次运行一个文件夹，内含两个 Markdown
    - 01_知识整合.md：概念树 → 文献 → 缺口（输入侧地图）
    - 02_假设生成.md：缺口 → 每轮假设/评审 → 分数轨迹 → 最佳版本（输出侧结论）
    返回文件夹路径。
    """
    os.makedirs(LOG_DIR, exist_ok=True)
    folder = result.get("run_folder")
    if folder and os.path.isdir(folder):
        # L5：main 预创建了运行文件夹（评审 JSONL 已写入），直接复用，避免序号错位
        run_no = result.get("run_no")
    else:
        # 兼容旧路径：自行分配
        run_no = next_run_number(LOG_DIR)
        ts = time.strftime("%Y%m%d_%H%M%S")
        topic = short_topic(question)
        base = f"运行{run_no:02d}"
        tag = f"{topic}{quality_target}"
        day_dir = os.path.join(LOG_DIR, time.strftime("%Y-%m-%d"))
        os.makedirs(day_dir, exist_ok=True)
        folder = os.path.join(day_dir, f"{base}_{tag}_{ts}")
        os.makedirs(folder, exist_ok=True)

    # ========== 01 知识整合 ==========
    p1 = os.path.join(folder, "01_知识整合.md")
    k1 = ["# 01 · 知识整合（概念树 → 文献 → 缺口）", ""]
    k1.append(f"- **根问题**：{result.get('question', '')}")
    tree = result.get("knowledge_tree")
    if not isinstance(tree, dict) or not tree.get("sub_problems"):
        k1.append("")
        k1.append("（本轮未执行知识整合）")
    else:
        k1.append("")
        k1.append(f"- **问题分析**：{tree.get('analysis', '（无）')}")
        gaps = result.get("knowledge_gaps") or []
        k1.append("")
        k1.append(f"- **知识缺口（{len(gaps)} 个）**：{'；'.join(gaps) if gaps else '无（文献覆盖充分）'}")
        k1.append("")
        k1.append(f"- **文献池**：{len(result.get('literature', []))} 篇")
        k1.append("")
        k1.append("## 概念树")
        for sp in tree.get("sub_problems", []):
            cov = sp.get("coverage", "")
            tag_cov = {"covered": "已覆盖", "partial": "部分覆盖", "gap": "缺口"}.get(cov, cov)
            k1.append("")
            k1.append(f"### [{sp.get('id')}] {sp.get('name', '')}（{tag_cov}）")
            if sp.get("concepts"):
                k1.append(f"- 概念：{'、'.join(sp['concepts'])}")
            if sp.get("aliases"):
                k1.append(f"- 别名：{'、'.join(sp['aliases'])}")
            if sp.get("search_keywords"):
                k1.append(f"- 检索词：{'、'.join(sp['search_keywords'])}")
            if sp.get("verifiable_angles"):
                k1.append(f"- 可检验角度：{'；'.join(sp['verifiable_angles'])}")
            papers = sp.get("papers", [])
            if papers:
                k1.append("- 文献：")
                for p in papers:
                    title = p.get("标题") or p.get("title") or "无标题"
                    journal = p.get("期刊") or p.get("journal") or ""
                    year = p.get("年份") or p.get("year") or ""
                    k1.append(f"  - 《{title}》（{journal} {year}）")
            else:
                k1.append("- 文献：暂无（知识缺口）")
    with open(p1, "w", encoding="utf-8") as f:
        f.write("\n".join(k1))

    # ========== 02 假设生成与评审迭代 ==========
    p2 = os.path.join(folder, "02_假设生成.md")
    lines = ["# 02 · 假设生成与评审迭代", ""]
    lines.append(f"- **问题**：{question}")
    lines.append(f"- **质量目标**：{quality_target} 分")
    lines.append(f"- **运行时间**：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    gap = result.get("gap", "")
    lines.append("## 研究缺口")
    lines.append("")
    lines.append(gap or "（无缺口分析）")
    lines.append("")

    hist = result.get("score_history", [])
    lines.append("## 分数迭代")
    if hist:
        lines.append("")
        lines.append("| 轮次 | 假设分 | 数据分 | 放行状态 |")
        lines.append("| --- | --- | --- | --- |")
        for h in hist:
            status = h.get("plan_status")
            if not status:
                status = "validated" if h["hypothesis_score"] >= quality_target and h.get("data_score", 0) >= 60 else "in_progress"
            mark = {
                "validated": "验证通过",
                "exploratory": "探索性（证据不足）",
                "in_progress": "未完成",
            }.get(status, status)
            if h.get("score_corrected"):
                mark += " ⚠修正"
            lines.append(f"| {h['round']} | {h['hypothesis_score']} | {h['data_score']} | {mark} |")
    else:
        lines.append("（无评审轮次）")
    lines.append("")

    best_score = result.get("best_score", 0)
    rounds = result.get("rounds", 0)
    plan_status = result.get("plan_status") or "in_progress"
    if plan_status == "validated":
        reason = f"验证通过：假设分 {best_score}，原始证据分 {result.get('best_data_score', 0)}"
    elif plan_status == "exploratory":
        reason = f"探索性完成：假设质量达到目标，但原始证据分仅 {result.get('best_data_score', 0)}，不能视为验证通过"
    elif rounds >= MAX_ROUNDS:
        reason = f"到达最大轮数上限（MAX_ROUNDS={MAX_ROUNDS}），未达标"
    else:
        reason = "提前收敛（连续多轮无提升）"
    lines.append(f"**结束原因**：{reason}")
    lines.append(f"**历史最高分版本**：假设分 {result.get('best_score', 0)}（数据分 {result.get('best_data_score', 0)}）")
    lines.append(f"**放行状态**：{plan_status}")
    if result.get("release_reason"):
        lines.append(f"**状态说明**：{result.get('release_reason')}")
    dims = result.get("dimensions")
    if isinstance(dims, dict):
        lines.append(f"**最近一轮四维**：可检验 {dims.get('testability')} / 依据 {dims.get('evidence')} / 可行 {dims.get('feasibility')} / 新颖 {dims.get('novelty')}（bottleneck：{result.get('bottleneck', '')}）")
    lines.append("")

    lines.append("## 过程原文（按轮次）")
    lines.append("")
    for r, entries in group_run_entries(RUN_LOG):
        if r == 0:
            for e in entries:
                if e["stage"] == "缺口分析":
                    lines.append("### 缺口分析")
                    lines.append("")
                    lines.append("```")
                    lines.append(str(e.get("text", "")))
                    lines.append("```")
                    lines.append("")
            continue
        lines.append(f"### 第 {r} 轮")
        lines.append("")
        for e in entries:
            st = e["stage"]
            if st == "知识整合":
                continue          # 知识整合专属 01 文档
            if st == "假设生成":
                lines.append(f"**第 {r} 轮 · 假设生成**")
            elif st == "评审":
                mark = "✅" if e.get("passed") else ""
                bneck = f"，bottleneck={e.get('bottleneck')}" if e.get("bottleneck") else ""
                lines.append(f"**第 {r} 轮 · 评审 {mark}（假设 {e.get('hypothesis_score')} / 数据 {e.get('data_score')}{bneck}）**")
                if e.get("points"):
                    lines.append("")
                    lines.append("评审要点逐项打分：")
                    for p in e["points"]:
                        last = p["history"][-1]
                        lines.append(f"- {p['id']}. {p['name']}：{last['score']} 分（第 {last['round']} 轮）")
            else:
                lines.append(f"**{st}**")
            lines.append("")
            lines.append("```")
            lines.append(str(e.get("text", "")))
            lines.append("```")
            lines.append("")

    hyp_hist = result.get("hypothesis_history", [])
    if hyp_hist:
        lines.append("## 假设版本历史")
        lines.append("")
        for i, h in enumerate(hyp_hist, 1):
            lines.append(f"**第 {i} 版（被下一版替换前）**：")
            lines.append("")
            lines.append("```")
            lines.append(str(h))
            lines.append("```")
            lines.append("")

    best_hyp = result.get("best_hypothesis")
    if best_hyp:
        lines.append("## 最佳版本（历史最高分）")
        lines.append("")
        lines.append("```")
        lines.append(str(best_hyp))
        lines.append("```")
        lines.append("")

    with open(p2, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ========== 03 可验证性验证 ==========
    p3 = os.path.join(folder, "03_可验证性验证.md")
    v3 = ["# 03 · 可验证性验证（Data Verify）", ""]
    verify = result.get("verification")
    if isinstance(verify, dict) and (verify.get("claims") or verify.get("summary")):
        v3.append(format_verification(verify))
    else:
        v3.append("（本轮未达标或未执行可验证性验证）")

    # evidence 88 说明（交付层，纯代码推导，不侵入打分逻辑）
    v3.append("")
    v3.append("## 关于 evidence 88 的说明")
    v3.append("")
    last_dims = result.get("dimensions")
    if isinstance(last_dims, dict) and isinstance(last_dims.get("evidence"), int) and last_dims["evidence"] == 88:
        nodes = _tree_gap_debate_nodes(result.get("knowledge_tree"), str(result.get("hypothesis") or ""))
        if nodes:
            v3.append("本轮依据维度（evidence）为 88，原因是假设涉及的知识树节点存在以下 ◇争议/✗缺口/部分覆盖：")
            v3.append("")
            for n in nodes:
                v3.append(f"- {n}")
            v3.append("")
            v3.append("按评分规则，涉及争议/缺口的情形下 evidence 封顶 88（不能给 89-92）。这是该文献/争议状态下的证据上限，不代表假设质量差；若要突破，需要先在知识整合阶段补齐对应文献或消除争议。")
        else:
            v3.append("本轮依据维度（evidence）为 88，但知识树不存在 ◇争议/✗缺口（满足松绑条件）——该 88 是评审按加分项逐分累计的结果，并非被上限封顶。")
    else:
        v3.append("本轮最终依据维度非 88，或为数据模式轮，本说明不适用。")
    with open(p3, "w", encoding="utf-8") as f:
        f.write("\n".join(v3))

    # ========== 05 最终交付：状态驱动的确定性摘要，不依赖 history[-1] 里的 Final Answer ==========
    p5 = os.path.join(folder, "05_最终交付.md")
    final_answer = str(result.get("final_answer") or "").strip()
    if not final_answer:
        final_answer = build_final_delivery(result)
    result["final_answer"] = final_answer
    with open(p5, "w", encoding="utf-8") as f:
        f.write(final_answer + "\n")

    # ========== 06 锚点与预实验核查：记录代码硬门命中与处理依据 ==========
    p6 = os.path.join(folder, "06_锚点与预实验核查报告.md")
    with open(p6, "w", encoding="utf-8") as f:
        f.write(anchor_checker.format_report(result))

    # ========== state.json：结构化状态存档（研究计划 12 字段后续单独生成的数据源） ==========
    # 主线只保证「假设 + 知识树」两个核心产物落盘；研究计划生成拆到独立步骤（--make-plan），
    # 读本文件即可复现 12 字段，无需重跑流水线，也方便批量生成与 debug。
    state_path = os.path.join(folder, "state.json")
    try:
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        # 个别字段不可序列化时，退而只存核心产物
        core = {k: result.get(k) for k in (
            "question", "quality_target", "knowledge_tree", "knowledge_gaps", "literature",
            "gap", "best_hypothesis", "best_score", "best_data_score", "verification",
            "dimensions", "bottleneck", "score_history", "hypothesis", "hypothesis_history", "points")}
        with open(state_path, "w", encoding="utf-8") as f:
            json.dump(core, f, ensure_ascii=False, indent=2)

    return folder



# ============ 搭图 + 编译 ============
builder = StateGraph(AgentState)
builder.add_node("llm", call_llm)
builder.add_node("tool", call_tool_node)
builder.add_node("knowledge", knowledge_integration)   # 知识整合：问题→概念树→逐节点检索→缺口标注
builder.add_node("papers", parse_papers)              # 论文解析：≤3 篇用户论文 → 知识卡 → 跨篇融合
builder.add_node("frontier", frontier_scan_node)     # 前沿风向扫描：最近 N 年 ~10 篇 → LLM 总结风向（旁路）
builder.add_node("verify", data_verify)             # 可验证性求证：达标后执行
builder.add_node("gap", gap_analysis)
builder.add_node("hypothesis", hypothesis_gen)          # 新工位
builder.add_node("review", review_hypothesis)           # 新工位：评审
builder.add_edge(START, "llm")
builder.add_conditional_edges("llm", route, {"tool": "tool", "papers": "papers", "gap": "knowledge"})
builder.add_edge("tool", "llm")
builder.add_edge("papers", "knowledge")                # 论文解析完，进知识整合
builder.add_edge("knowledge", "frontier")               # 知识整合完，先做前沿风向扫描
builder.add_edge("frontier", "gap")                     # 前沿扫描完，进缺口分析
builder.add_edge("gap", "hypothesis")                   # 缺口分析完，进假设生成
builder.add_edge("hypothesis", "review")                # 假设生成完，进评审
builder.add_conditional_edges("review", route_review, {
    "hypothesis": "hypothesis",                         # 回炉改假设
    "llm": "llm",                                       # 回去补搜
    "verify": "verify",                                 # 达标 → 可验证性求证
    END: END,                                           # 收敛/上限，放行
})
builder.add_edge("verify", END)                         # 验证完收工（研究计划 12 字段留到最后统一生成，见 --make-plan）
graph = builder.compile()   # 把搭好的图"交付"成可运行的 graph



# ============ P8 锚定探针：把极弱/极强假设直接喂给评审，看分数是否被默认值吸住 ============
PROBE_CASES = [
    {
        "question": "钙钛矿太阳能电池的长期稳定性如何提升？",
        "gap": "现有文献主要聚焦于制备工艺优化，长期湿热加光照耦合老化下的降解机制缺乏标准化测试与数据。",
        "literature": [
            {"标题": "The emergence of perovskite solar cells", "期刊": "Nature Photonics", "年份": 2014},
            {"标题": "Cesium-containing triple cation perovskite solar cells", "期刊": "Energy & Environmental Science", "年份": 2016},
            {"标题": "Degradation mechanisms of perovskite solar cells under damp heat and illumination", "期刊": "Joule", "年份": 2020},
            {"标题": "Ion migration in metal halide perovskites: a review", "期刊": "Advanced Energy Materials", "年份": 2021},
            {"标题": "In situ mass spectrometry of gas evolution from metal halide perovskites", "期刊": "Nature Communications", "年份": 2022},
            {"标题": "ISOS protocols for stability testing of photovoltaic devices", "期刊": "Solar Energy Materials and Solar Cells", "年份": 2020},
            {"标题": "Ultra-thin Al2O3 passivation for perovskite solar cells", "期刊": "Advanced Materials Interfaces", "年份": 2018},
        ],
        "弱": "通过优化材料组成和制备工艺，可以提高钙钛矿太阳能电池的稳定性和效率。",
        "强": "在85度/85%RH湿热与1个太阳光照耦合老化条件下，A位混合三阳离子（Cs/MA/FA）钙钛矿薄膜的降解速率主要由FA正离子脱质子反应触发，界面处引入3 nm超薄Al2O3钝化层后，NH3释放速率降低2个数量级，T80寿命从低于500小时延长至高于2000小时；验证方法：IEC 61215耦合老化箱原位质谱监测NH3，ToF-SIMS追踪碘离子与FA正离子迁移深度。",
    },
    {
        "question": "锂离子电池的剩余寿命如何更准确预测？",
        "gap": "多数模型依赖实验室加速老化数据，缺乏真实工况下非线性老化的鲁棒性验证，且缺乏跨化学体系的通用预测框架。",
        "literature": [
            {"标题": "Data-driven health estimation and lifetime prediction of lithium-ion batteries: A review", "期刊": "Renewable and Sustainable Energy Reviews", "年份": 2019},
            {"标题": "A review of physics-based models for lithium-ion battery lifetime prediction", "期刊": "Journal of Power Sources", "年份": 2021},
            {"标题": "Feature engineering for early prediction of lithium-ion battery remaining useful life", "期刊": "Nature Energy", "年份": 2020},
            {"标题": "Transfer learning for cross-chemistry battery lifetime prediction", "期刊": "Energy Storage Materials", "年份": 2022},
            {"标题": "SEI growth mechanisms and capacity fade in lithium-ion batteries", "期刊": "Electrochimica Acta", "年份": 2019},
            {"标题": "Lifetime prediction under dynamic load and temperature profiles", "期刊": "Applied Energy", "年份": 2021},
            {"标题": "A benchmark dataset for remaining useful life prediction of lithium-ion batteries", "期刊": "Journal of Power Sources", "年份": 2016},
        ],
        "弱": "用机器学习方法可以更好地预测锂离子电池的剩余寿命。",
        "强": "在动态负载与温度波动耦合的真实工况下，以SEI增长速率与析锂阈值之比作为输入特征，可显著提升数据驱动模型对早期（容量衰减低于20%）非线性老化的预测精度，预测误差较纯数据驱动模型降低至少30%；验证方法：NASA PCoE公开数据集5折交叉验证加1年实测数据外推。",
    },
    {
        "question": "锂金属电池的枝晶问题如何抑制？",
        "gap": "现有研究多从单一维度（电解液或压力）抑制枝晶，缺乏电解液组分与力学约束耦合的定量规律。",
        "literature": [
            {"标题": "Reviving the lithium metal anode for high-energy batteries", "期刊": "Nature Nanotechnology", "年份": 2017},
            {"标题": "A review of lithium deposition and stripping mechanisms", "期刊": "Advanced Energy Materials", "年份": 2020},
            {"标题": "Fluoroethylene carbonate as a key additive for stable lithium metal anodes", "期刊": "Journal of The Electrochemical Society", "年份": 2018},
            {"标题": "Mechanical pressure effects on dendrite growth in lithium metal batteries", "期刊": "Joule", "年份": 2021},
            {"标题": "In situ optical microscopy of lithium dendrite growth", "期刊": "Nature Communications", "年份": 2019},
            {"标题": "Synchrotron X-ray tomography of lithium metal anodes", "期刊": "Advanced Materials", "年份": 2021},
            {"标题": "Quantifying porosity evolution in lithium metal electrodes", "期刊": "ACS Energy Letters", "年份": 2020},
        ],
        "弱": "通过改变电解液配方，可以减少锂金属电池的枝晶生长。",
        "强": "将氟代碳酸乙烯酯（FEC）浓度从5%提升至15%并配合30 MPa堆叠压力时，锂金属负极在2 mA每平方厘米、4 mAh每平方厘米条件下循环寿命从80次延长至500次，枝晶穿透概率从65%降至8%；验证方法：原位光学显微镜监测枝晶生长，同步辐射X射线断层扫描定量孔隙率，对称电池长循环。",
    },
]

def save_probe_log(results):
    """P8 探针也落盘到 27日\生成日志，方便直接读文件而不是翻终端"""
    os.makedirs(LOG_DIR, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    fname = f"P8锚定探针_{ts}.md"
    fpath = os.path.join(LOG_DIR, fname)
    lines = []
    lines.append("# P8 锚定探针日志")
    lines.append("")
    lines.append(f"- **运行时间**：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## 汇总")
    lines.append("")
    lines.append("| 题目 | 强度 | 假设分 | 数据分 |")
    lines.append("| --- | --- | --- | --- |")
    for q, s, h, d in results:
        lines.append(f"| {q} | {s} | {h} | {d} |")
    lines.append("")
    lines.append("## 各次评审原文")
    lines.append("")
    for e in RUN_LOG:
        if e["stage"] == "评审":
            lines.append(f"### 第 {e['round']} 次评审")
            lines.append("")
            lines.append("```")
            lines.append(e["text"])
            lines.append("```")
            lines.append("")
    with io.open(fpath, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))
    return fpath


def run_anchor_probe():
    print("=" * 66)
    print("P8 锚定探针：同一评审提示词，分别喂极弱/极强假设，看分数是否被默认值吸住")
    print("=" * 66)
    results = []
    for case in PROBE_CASES:
        for strength in ["弱", "强"]:
            state = {
                "question": case["question"],
                "gap": case["gap"],
                "literature": case["literature"],
                "hypothesis": case[strength],
                "hypothesis_history": [],
                "history": [],
                "review": [],
                "points": [],
                "score_history": [],
                "rounds": 0,
                "quality_target": 90,
                "steps": 0,
                "hypothesis_score": 0,
                "data_score": 0,
            }
            print(f"\n--- 题目：{case['question']}  |  假设强度：{strength} ---")
            out = review_hypothesis(state)
            results.append((case["question"], strength, out["hypothesis_score"], out["data_score"]))
    print("\n" + "=" * 66)
    print("汇总：")
    print(f"{'题目':<22} {'强度':<4} {'假设分':>6} {'数据分':>6}")
    for q, s, h, d in results:
        print(f"{q[:20]:<22} {s:<4} {h:>6} {d:>6}")
    weak = [r for r in results if r[1] == "弱"]
    strong = [r for r in results if r[1] == "强"]
    w_avg = sum(r[2] for r in weak) / len(weak)
    s_avg = sum(r[2] for r in strong) / len(strong)
    print(f"\n极弱假设平均分：{w_avg:.1f}，极强假设平均分：{s_avg:.1f}")
    if s_avg - w_avg >= 10:
        print("结论方向：评审能区分强弱（未明显锚定）")
    else:
        print("结论方向：评审疑似被默认分吸住（锚定）")

    log_path = save_probe_log(results)
    print(f"[日志] 探针日志已保存：{log_path}")

def main():
    # 冻结 exe（PyInstaller）在中文 Windows 下管道 stdout 固定 GBK，PYTHONIOENCODING 不生效；
    # 这里强制 UTF-8 + replace，防止打印含重音字符（如 É）的 LLM 内容时 UnicodeEncodeError 中断整轮。
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


        if "--probe" in sys.argv:
            run_anchor_probe()
            sys.exit()

        if "--graph" in sys.argv:
            print(graph.get_graph().draw_mermaid())
            sys.exit()

        if "--make-plan" in sys.argv or "--make-plan-all" in sys.argv:
            # 独立生成 12 字段研究计划：
            #   --make-plan <运行文件夹>                     单文件夹
            #   --make-plan-all <日志目录> [--force]          批量：扫描目录下所有含 state.json 的文件夹
            force = "--force" in sys.argv
            if "--make-plan-all" in sys.argv:
                idx = sys.argv.index("--make-plan-all")
                if idx + 1 >= len(sys.argv) or not os.path.isdir(sys.argv[idx + 1]):
                    print("用法：python langgraph_agent.py --make-plan-all <日志目录> [--force]")
                    sys.exit(1)
                root = sys.argv[idx + 1]
                ok = fail = skip = 0
                for name in sorted(os.listdir(root)):
                    folder = os.path.join(root, name)
                    if not os.path.isdir(folder) or not os.path.isfile(os.path.join(folder, "state.json")):
                        continue
                    if not force and os.path.isfile(os.path.join(folder, "04_研究计划.md")):
                        skip += 1
                        continue
                    plan_path, text = generate_plan_from_folder(folder)
                    if plan_path:
                        print(f"[研究计划] 已生成：{plan_path}")
                        ok += 1
                    else:
                        print(f"[研究计划] 失败：{folder} -> {text}")
                        fail += 1
                print(f"\n[研究计划] 批量完成：生成 {ok}，失败 {fail}，跳过(已有) {skip}")
                sys.exit(1 if fail else 0)
            idx = sys.argv.index("--make-plan")
            if idx + 1 >= len(sys.argv):
                print("用法：python langgraph_agent.py --make-plan <运行文件夹路径>（该文件夹内需有 state.json）")
                sys.exit(1)
            folder = sys.argv[idx + 1]
            plan_path, text = generate_plan_from_folder(folder)
            if plan_path:
                print(f"[研究计划] 已生成：{plan_path}")
            else:
                print(f"[研究计划] 失败：{text}")
            sys.exit(0 if plan_path else 1)

        quality_map = {"一般": 70, "好": 80, "超好": 90, "顶级": 92}
        quality_target = 80                                   # 默认"好"
        knowledge_enabled = True                              # --no-knowledge 时关闭（A/B 对照）
        frontier_years = 3                                     # --frontier-years N：前沿风向扫描的年份窗口（1/2/3）
        QUESTION = "找一篇关于锂离子电池寿命预测的论文，告诉我标题和 DOI"
        papers_path = None                                   # --papers <json路径>：用户论文（api_server 传入）
        clarify_path = None                                  # --clarify <json路径>：追问 Q&A（api_server 传入）
        question_en = ""                                     # --question-en：前端翻译的英文问题（中文文献池双语检索用）
        i = 1
        while i < len(sys.argv):
            if sys.argv[i] == "--quality" and i + 1 < len(sys.argv):
                quality_target = quality_map.get(sys.argv[i + 1], 80)
                i += 2
            elif sys.argv[i] == "--no-knowledge":
                knowledge_enabled = False
                i += 1
            elif sys.argv[i] == "--papers" and i + 1 < len(sys.argv):
                papers_path = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--clarify" and i + 1 < len(sys.argv):
                clarify_path = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--question-en" and i + 1 < len(sys.argv):
                question_en = sys.argv[i + 1].strip()
                i += 2
            elif sys.argv[i] == "--frontier-years" and i + 1 < len(sys.argv):
                try:
                    frontier_years = max(1, min(int(sys.argv[i + 1]), 5))
                except (TypeError, ValueError):
                    frontier_years = 3
                i += 2
            else:
                QUESTION = sys.argv[i]
                i += 1
        # 问题语言检测（2026-08-30）：含中文字符 → 中文文献池双语检索
        import re as _re_lang
        question_lang = "zh" if _re_lang.search(r"[\u4e00-\u9fff]", QUESTION) else "en"
        # L5：运行前预分配 run_no 并创建运行文件夹（评审节点据此落盘 03_评审JSONL.jsonl）
        os.makedirs(LOG_DIR, exist_ok=True)
        run_no = next_run_number(LOG_DIR)
        day_dir = os.path.join(LOG_DIR, time.strftime("%Y-%m-%d"))
        os.makedirs(day_dir, exist_ok=True)
        ts = time.strftime("%Y%m%d_%H%M%S")
        topic = short_topic(QUESTION)
        tag = f"{topic}{quality_target}"
        run_folder = os.path.join(day_dir, f"运行{run_no:02d}_{tag}_{ts}")
        os.makedirs(run_folder, exist_ok=True)

        given_papers = []
        if papers_path and os.path.isfile(papers_path):
            try:
                with io.open(papers_path, encoding="utf-8") as f:
                    _gp = json.load(f)
                if isinstance(_gp, list):
                    given_papers = [str(x).strip() for x in _gp if str(x).strip()][:3]
            except Exception:
                given_papers = []
        if given_papers:
            print(f"[论文输入] 已加载 {len(given_papers)} 篇用户论文")
        clarify_qa = []
        if clarify_path and os.path.isfile(clarify_path):
            try:
                with io.open(clarify_path, encoding="utf-8") as f:
                    _cq = json.load(f)
                if isinstance(_cq, list):
                    clarify_qa = [{"question": str(x.get("question") or "").strip(),
                                   "answer": str(x.get("answer") or "").strip()}
                                  for x in _cq if isinstance(x, dict) and str(x.get("answer") or "").strip()]
            except Exception:
                clarify_qa = []
        if clarify_qa:
            print(f"[追问精修] 已加载 {len(clarify_qa)} 条补充说明")

        try:
            result = graph.invoke({
                "question": QUESTION,
                "history": [],
                "steps": 0,
                "literature": [],
                "gap": "",
                "hypothesis": "",
                "hypothesis_history": [],
                "review": [],
                "rounds": 0,
                "status": "搜索",
                "quality_target": quality_target,
                "hypothesis_score": 0,
                "data_score": 0,
                "feedback": "",
                "last_feedback_ts": 0,
                "adj_cache": None,
                "score_history": [],
                "best_hypothesis": "",
                "best_score": 0,
                "best_data_score": 0,
                "anchor_blocked": False,
                "anchor_issues": [],
                "points": [],
                "revision_notes": "",
                "literature_changed": True,
                "prev_literature_hash": "",
                "data_review": [],
                "dimensions": None,
                "bottleneck": "",
                "consecutive_data_rounds": 0,
                "total_data_rounds": 0,
                "search_requested": False,
                "search_keywords": [],
                "soft_search_rounds": 0,
                "total_soft_searches": 0,
                "search_exhausted": False,
                "platform_declared": False,
                "platform_suggestion": "",
                "platform_active": False,
                "knowledge_tree": None,
                "knowledge_gaps": [],
                "knowledge_done": False,
                "knowledge_enabled": knowledge_enabled,
                "research_plan": None,
                "research_plan_text": "",
                "run_no": run_no,
                "run_folder": run_folder,
                "tree_version": 0,
                "tree_rebuild_pending": False,
                "knowledge_tree_mark": "",
                "last_new_relevant": 0,
                "gap_confirmed_latched": False,
                "frontier_years": frontier_years,
                "question_lang": question_lang,
                "question_en": question_en,
                "filtered_out": [],
                "probe_count": 0,
                "points_healthcheck_round": 0,
                "given_papers": given_papers,
                "paper_cards": [],
                "paper_fusion": {},
                "paper_parse_done": False,
                "clarify_qa": clarify_qa,
            })
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            print("[运行失败] " + str(e))
            print(tb)
            try:
                err_file = os.path.join(run_folder, "run_error.txt")
                with open(err_file, "w", encoding="utf-8") as f:
                    f.write(str(e) + "\n\n" + tb[-3000:])
                state_err = os.path.join(run_folder, "state.json")
                with open(state_err, "w", encoding="utf-8") as f:
                    json.dump({
                        "question": QUESTION, "run_no": run_no, "run_folder": run_folder,
                        "status": "error", "error": str(e),
                    }, f, ensure_ascii=False, indent=2)
                print("[运行失败] 已写错误存档: " + err_file)
            except Exception as e2:
                print("[运行失败] 写错误存档失败: " + str(e2))
            sys.exit(3)

        _u = llm_client.get_usage()
        _pt = int(_u.get("prompt_tokens", 0) or 0)
        _ct = int(_u.get("completion_tokens", 0) or 0)
        _total = _pt + _ct
        _rate = float(os.getenv("AI_COST_CNY_PER_M", "0.24"))
        result["api_usage"] = {"prompt_tokens": _pt, "completion_tokens": _ct, "calls": int(_u.get("calls", 0) or 0)}
        result["api_cost_cny"] = round(_total * _rate / 1000000.0, 6)
        _write_progress(result, "完成",
                        f"假设分 {result.get('best_score', 0)} / 数据分 {result.get('best_data_score', 0)}"
                        f" / 状态 {result.get('plan_status', 'in_progress')}"
                        f" · 本次消费 ¥{result['api_cost_cny']}")
        # 从最终白板里把 Final Answer 抠出来
        _safe_print("\n[白板] 跑完后的完整状态：")
        for k, v in result.items():
            _safe_print(f"  {k}: {v}")

        log_path = save_run_log(result, QUESTION, quality_target)
        print(f"[日志] 本次运行日志已保存：{log_path}")

        try:
            from citation_checker import write_citation_report
            citation_path = write_citation_report(run_folder)
            print(f"[引用归属核查] 已保存：{citation_path}")
        except Exception as _citation_exc:
            print(f"[引用归属核查] 生成失败（不影响主流程）：{_citation_exc}")

        try:
            from plan_quality_checker import write_report as write_quality_report
            quality_path = write_quality_report(run_folder)
            print(f"[统计与数字一致性核查] 已保存：{quality_path}")
        except Exception as _quality_exc:
            print(f"[统计与数字一致性核查] 生成失败（不影响主流程）：{_quality_exc}")

        try:
            from data_source_checker import write_data_source_report
            data_source_path = write_data_source_report(run_folder)
            print(f"[数据源与可观测性核查] 已保存：{data_source_path}")
        except Exception as _data_source_exc:
            print(f"[数据源与可观测性核查] 生成失败（不影响主流程）：{_data_source_exc}")

        try:
            from reviewer_report import write_reviewer_report
            reviewer_html, _reviewer_md = write_reviewer_report(run_folder, as_md=True)
            print(f"[独立评审报告] 已保存：{reviewer_html}")
        except Exception as _reviewer_exc:
            print(f"[独立评审报告] 生成失败（不影响主流程）：{_reviewer_exc}")

        chart = plot_scores(result.get("score_history", []), quality_target, log_path)
        if chart:
            print(f"\n[图表] 分数迭代曲线已保存：{chart}")

        if result.get("best_hypothesis"):
            print(f"\n[最佳版本] 历史最高分：{result.get('best_score')}（数据分 {result.get('best_data_score')}），已存档")

        final_answer = str(result.get("final_answer") or "").strip()
        if not final_answer and result.get("history"):
            last = result["history"][-1]
            if "final answer" in last.lower():
                final_answer = last.split("Final Answer", 1)[-1].strip(":： \n")
        if final_answer:
            _safe_print(f"\n==> 最终交付：\n{final_answer}")
        else:
            _safe_print("\n[注意] 本次运行没有形成可交付摘要，请检查运行日志。")



if __name__ == "__main__":
    main()
