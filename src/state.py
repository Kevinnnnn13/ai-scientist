"""state.py：定义科研助手的「白板」（全局状态）"""

from typing import TypedDict

class AgentState(TypedDict):
    question: str        # 用户问题
    history: list[str]   # 这一轮的对话记录（短期记忆）
    steps: int           # 已经跑了多少轮

    literature: list[dict]  #搜到的文献列表（每篇是一个字典）
    gap: str  # 研究空白
    hypothesis: str  # 研究假设
    hypothesis_history: list[str]  # 每版假设的历史存档（评审对比“上一版→当前版”用）
    review: list[str]  #评审意见，可能有多条
    rounds: int      #评审轮数
    status: str  #当前阶段：如"搜索"，"评审"，"完成"
    quality_target: int       # 用户选的及格线（70/80/90/92）
    hypothesis_score: int     # 最近一轮评审给假设的打分
    data_score: int           # 最近一轮评审给数据充分性的打分
    feedback: str             # 给 llm 的回传指令（如"文献为空，回去补搜"）
    score_history: list[dict] # 每轮评审的分数记录：[{"round":1,"hypothesis_score":70,"data_score":0}, ...]
    best_hypothesis: str      # 历史最高分版本的假设（存档，防止改差后丢失）
    best_score: int           # 历史最高分
    best_data_score: int      # 历史最高分那一轮的数据分
    plan_status: str          # 放行状态：validated / exploratory / in_progress
    evidence_status: str      # 证据状态：verified / insufficient_evidence / searching
    release_reason: str       # 给用户与日志看的放行/未放行原因
    anchor_blocked: bool      # 是否被未经核验的图表/补充材料/既成实验事实钉住
    anchor_issues: list       # 锚点核查发现的硬问题明细（代码确定性命中）
    points: list[dict]        # 评审要点清单（只增不减）：[{"id":1,"name":"可检验性","history":[{"round":1,"score":85},...]}, ...]

    revision_notes: str        # 生成器本轮声称的修改说明（评审核对「声称已修 vs 实际已修」）
    literature_changed: bool   # 本轮文献相对上一轮是否变化（评审防 data 漂移）
    prev_literature_hash: str  # 上一轮文献的序列化哈希
    data_review: list[str]     # 数据不足轮次的补搜建议（补搜回来后拼给生成器）
    dimensions: dict           # 最近一轮评审的四维分
    bottleneck: str            # 最近一轮评审判定的瓶颈维度
    consecutive_data_rounds: int  # 连续几轮补搜无新文献（搜索循环上限用）
    total_data_rounds: int        # 全局补搜轮数（搜索总预算，MAX_DATA_ROUNDS 上限）
    gap_confirmed_latched: bool   # 2026-08-29：文献缺口已确认的粘滞标记（转档后保持，文献池有相关新增才解除）
    search_requested: bool        # P9 软搜索：本轮评审是否请求补搜（结构化 search_request / 词法兜底）
    search_keywords: list[str]    # P9 软搜索：评审给的搜索关键词
    soft_search_rounds: int       # P9 软搜索：同一缺口已软搜几轮（文献未变则累计）
    search_exhausted: bool        # P9 软搜索：预算耗尽/同关键词多轮无新文献 -> 缺口已确认，转收窄
    knowledge_tree: dict          # 知识整合：概念树（根问题→子问题→概念→文献→覆盖状态）
    knowledge_gaps: list[str]     # 知识整合：文献未覆盖的知识缺口清单
    knowledge_done: bool          # 知识整合：是否已完成首轮拆解+检索（幂等标记）
    # ---- 前沿风向扫描（2026-08-29 旁路模块）----
    frontier_ready: bool          # 前沿扫描是否成功产出（False=跳过，主流程不受影响）
    frontier_years: int           # 前沿扫描年份窗口（默认 3）
    frontier_report: dict         # 前沿扫描结构化报告（hotspots/method_trends/debates/representative）
    frontier_text: str            # 前沿扫描 markdown 文本（落盘 04_前沿风向.md）
    frontier_papers: list         # 前沿扫描检索到的论文列表
    frontier_error: str           # 前沿扫描错误信息（ready=False 时说明原因）
    verification: dict          # 可验证性验证（Data Verify）：达标假设的验证报告（summary/claims/results_preview）
    final_answer: str           # 最终交付摘要：按 validated / exploratory / in_progress 明确写出结论边界
    research_plan: dict          # 研究计划（Research Plan）：12 字段《科学假设与研究计划》JSON
    research_plan_text: str    # 研究计划的 Markdown 渲染（04_研究计划.md 用）
    knowledge_enabled: bool       # 知识整合开关（--no-knowledge 时 False，A/B 对照用）
    total_soft_searches: int      # P9 软搜索：全局软搜总次数（只增不减，MAX_TOTAL_SEARCH 上限）

    # ---- L5-L7（批次 C/D，2026-08-10）----
    run_no: int                    # L5：本次运行序号（main 预分配，供 JSONL 落盘）
    run_folder: str                # L5：本次运行文件夹（main 预创建，评审节点直接写 03_评审JSONL.jsonl）
    tree_version: int              # L7：知识树版本号（重拆 +1；收敛/平台期窗口同版本内比较）
    tree_rebuild_pending: bool     # L7：相关新增达标 -> 待重拆标记（llm 路由时送回 knowledge 节点）
    knowledge_tree_mark: str       # L7/N4：重拆轮注入「知识树已更新，分数变化可能是重估」标记（读一次后清除）
    last_new_relevant: int         # L6：最近一次搜索落池的「相关新增」篇数（cdr 语义 = 相关新增=0）
    filtered_out: list             # L6：被判定无关而未进池的文献记录（审计/日志用）
    probe_count: int               # L4：本轮 run 已执行的分歧探测次数（上限 2）
    points_healthcheck_round: int  # L3：上次对 archived 要点做健康复查的轮次

    # ---- 论文输入模块（2026-08-26）----
    given_papers: list[str]        # 用户输入的论文（≤3 篇，纯文本）
    paper_cards: list[dict]        # 论文解析：每篇一张结构化知识卡
    paper_fusion: dict             # 论文解析：跨篇融合（共识/矛盾/互补/共同缺口）
    paper_parse_done: bool         # 论文解析是否已完成（幂等标记）

    # ---- 追问精修模块（2026-08-28）----
    clarify_qa: list[dict]        # 追问环节的 Q&A：[{"question","answer"}]，喂给知识整合
