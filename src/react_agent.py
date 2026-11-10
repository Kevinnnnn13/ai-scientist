"""react_agent.py：原生 ReAct 智能体——"Agent 的脑子"（纯 Python，不用任何框架）

ReAct = Reason + Act：交替进行"思考"和"行动"：Thought（想）-> Action（做）-> Observation（看结果）-> 再想 -> ... -> Final Answer

第 7 天（今天）的设计：
  1. 长期记忆注入：开局把最近记过的东西塞进系统提示词（它一睁眼就知道自己记得什么）
  2. 判断步：第 1 轮先问 LLM"能不能只靠内置知识回答"，能就直接出答案，省 token
  3. 双上限 + y/n 交互：
     - 对话轮次上限 10（remember/recall 也算一轮）
     - 联网搜索上限 5（只有真联网的工具才算，且失败不计数）
     - 对话上限在每轮开头查；搜索上限在"它真的准备搜索"那一刻查
  4. 质检：Final Answer 后再问一次"覆盖完整吗"，不完整就回去补
  5. 拆解 + 自查：提示词要求它先列要点、收尾前逐条核对
用法：
  python src/react_agent.py "你的问题"          # 不带参数用默认问题
  python src/react_agent.py --clear "你的问题"    # 先清空长期记忆再跑（测试用）
  python src/react_agent.py "清空长期记忆"        # 只清空记忆
"""
import json
import re

from llm_client import chat
from tools import call_tool, list_tools
import memory          # 长期记忆（JSON 文件）

MAX_STEPS = 10         # 对话轮次上限（remember/recall 也算一轮）
MAX_SEARCHES = 5       # 联网搜索上限（只有真联网的工具才算）
NETWORK_TOOLS = {"search_web", "search_papers", "crossref_lookup"}


# ============ 系统提示词：告诉 LLM 它是谁、能干什么、怎么输出 ============
def build_system():
    """动态拼系统提示词 = 工具清单 + 最近记忆。
    用函数而不是写死字符串：每次调用都重新读一次记忆文件，
    保证 Agent 看到的记忆永远是"最新版"。
    """
    tools_text = list_tools()

    # 把最近 5 条记忆格式化成几行文字，让 LLM 开局就知道自己记得什么
    mem_lines = [f"- #{e['id']}（{e.get('time', '')}）{e['content']}"
                 for e in memory.recent_memory(5)]
    memory_text = "\n".join(mem_lines) if mem_lines else "（还没有任何记忆）"

    return f"""你是一个科研助手 Agent，可以调用以下工具：

{tools_text}

你的长期记忆（以前运行记下的内容，供你参考）：
{memory_text}

工作方式（每轮严格按此格式输出）：
要么是"行动"：
Thought: 你现在在思考什么
Action: 工具名
Action Input: {{"参数名": "参数值"}}

要么是"收尾"：
Thought: 你已经得到足够信息了
Final Answer: 你的最终答案

示例（行动轮）：
Thought: 用户要找钙钛矿太阳能电池的论文，我先搜索。
Action: search_papers
Action Input: {{"query": "perovskite solar cells", "per_page": 5}}

示例（收尾轮）：
Thought: 论文信息已齐全。
Final Answer: 标题：The emergence of perovskite solar cells；期刊：Nature Photonics；DOI：10.1038/nphoton.2014.134

规则：
1. 每轮只能输出一个 Action 或直接 Final Answer；
2. 工具结果会以 Observation 的形式返回给你；
3. 动手前先拆解用户要求，列出所有必须满足的要点；每个要点都必须有来源支撑（搜索或记忆）；
4. 写 Final Answer 前自查：用户要求的每个点都答到了吗？缺哪个点，就用针对性的新关键词搜索补齐；全部齐了，必须立刻 Final Answer 收尾，不许为了凑轮次或凑搜索次数继续搜索；
5. 最多 {MAX_STEPS} 轮；
6. 查到值得长期记住的关键信息（论文、DOI、结论），用 remember 存下来；
7. 任务和以前记过的内容有关，可以先 recall 查一下；但不要刚存完就重复 recall，不要用换关键词的方式重复搜索同一件事。"""


def parse_action(text):
    """从 LLM 输出里解析出 (工具名, 参数字典)。
    解析失败返回 None（交给上层处理，不让 Agent 崩）。
    """
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


def force_final(question, history):
    """到达上限且用户选择不继续时，让 LLM 基于已有过程直接收尾出答案。"""
    transcript = "\n".join(history) if history else "（还没有调用任何工具）"
    prompt = (f"用户问题：{question}\n\n"
              f"已经不能再继续搜索了，请基于下面的过程：\n{transcript}\n\n"
              "用 Final Answer 直接给出你现在能给出的最完整答案。")
    final = chat(prompt, system=build_system())
    print(f"\n==> 最终答案：{final}")
def run(question):
    history = []                      # 短期记忆：这一轮运行里的对话记录
    step = 0                          # 对话轮次计数
    search_count = 0                  # 联网搜索计数（只算成功的）
    step_limit = MAX_STEPS            # 对话上限（用户说 y 会 +10）
    search_limit = MAX_SEARCHES       # 搜索上限（用户说 y 会 +5）

    # ===== 循环：第 1 轮先判断能否只靠知识回答，能就直接结束 =====
    while True:
        step += 1

        # 每轮开始前只查"对话轮次"上限；搜索上限等它真想搜索那一刻再查
        if step > step_limit:
            print(f"\n[提示] 对话已达上限：第 {step - 1}/{step_limit} 轮。")
            while True:
                choice = input("是否继续（y/n）？").strip().lower()
                if choice in ("y", "yes"):
                    step_limit += 10      # 对话上限 +10
                    break
                elif choice in ("n", "no"):
                    force_final(question, history)
                    return
                else:
                    print("输入无效，只能输入 y 或 n，请重新输入。")

        print(f"\n===== 第 {step}/{step_limit} 轮对话 · 已成功联网搜索 {search_count}/{search_limit} 次 =====")

        # 第 1 轮：判断能否只靠内置知识回答
        if step == 1:
            knowledge_prompt = (f"用户问题：{question}\n\n"
                                "这个问题只靠你的内置知识就能给出准确完整的答案吗？\n"
                                "如果能，只回复：yes\n"
                                "如果必须搜索网页或查论文才能回答，只回复：no")
            verdict = chat(knowledge_prompt, system=build_system()).strip().lower()
            print(f"\n[判断] 能否只靠知识回答：{verdict}")
            if "yes" in verdict:
                answer_prompt = f"用户问题：{question}\n\n请直接给出准确、完整的答案。"
                final = chat(answer_prompt, system=build_system())
                print(f"\n==> 最终答案：{final}")
                return    # 简单问答不写记忆，直接结束

        # 1. 拼提示词：问题 + 之前所有轮次
        prompt = f"用户问题：{question}\n"
        if history:
            prompt += "\n之前的经过：\n" + "\n".join(history)
        prompt += "\n\n请输出你的下一步。"
        reply = chat(prompt, system=build_system())
        print(f"[LLM] {reply}")

        # 2. 直接给最终答案 -> 先质检，再决定结束还是回去补
        if "final answer" in reply.lower():
            final = reply.split("Final Answer", 1)[-1].split("final answer", 1)[-1]
            final = final.strip(":： \n")
            print(f"\n==> 最终答案：{final}")

            # 质检：再问 LLM 一次"覆盖完整吗"，不完整就把缺口喂回去继续补
            check_prompt = (f"用户问题：{question}\n\n"
                            f"这是 Agent 给出的最终答案：\n{final}\n\n"
                            "这个答案完整覆盖用户的所有要求了吗？\n"
                            "如果完整，只回复：complete\n"
                            "如果不完整，只回复还缺什么（一句话，具体，不要解释）。")
            check = chat(check_prompt, system=build_system()).strip().lower()
            print(f"\n[质检] 覆盖检查：{'完整' if 'complete' in check else '有缺口'}")
            if "complete" in check:
                break
            history.append(f"第{step}轮：{reply}\n质检发现缺口：{check}。请针对缺口继续搜索或补充，然后再给出 Final Answer。")
            continue

        # 3. 解析行动；解析失败就让它重来
        parsed = parse_action(reply)
        if parsed is None:
            history.append(f"第{step}轮输出无法解析，请直接给出 Final Answer 或重新输出 Action。")
            continue

        name, args = parsed
        print(f"-> 调用工具 {name}，参数：{args}")

        # 它想联网搜索，但"成功搜索"次数已到上限：先问用户，别让它烧第 N+1 次
        if name in NETWORK_TOOLS and search_count >= search_limit:
            print(f"\n[提示] 联网搜索已达上限：已成功搜索 {search_count}/{search_limit} 次。")
            while True:
                choice = input("是否继续搜索（y/n）？").strip().lower()
                if choice in ("y", "yes"):
                    search_limit += 5     # 搜索上限 +5
                    break
                elif choice in ("n", "no"):
                    force_final(question, history)
                    return
                else:
                    print("输入无效，只能输入 y 或 n，请重新输入。")

        result = call_tool(name, **args)

        # 4. 观察结果存进历史（截断防上下文爆掉）
        obs = json.dumps(result, ensure_ascii=False)
        if len(obs) > 2000:
            obs = obs[:2000] + "……(已截断)"
        print(f"-> Observation：{obs[:300]}……" if len(obs) > 300 else f"-> Observation：{obs}")
        history.append(f"第{step}轮：{reply}\nObservation: {obs}")

        # 5. 只有搜索"真的成功"才计数；失败（SSL 之类）不算烧额度
        if name in NETWORK_TOOLS and result.get("ok"):
            search_count += 1

    # ===== 收尾：反思 + 自动写进长期记忆 =====
    transcript = "\n".join(history) if history else "（本轮没有调用任何工具）"
    reflect_prompt = (f"用户问题：{question}\n\n"
                      f"刚才的执行过程：\n{transcript}\n\n"
                      "请用 2~3 句话总结：查到了什么、结论是什么、"
                      "有哪些值得以后记住的关键信息（论文/DOI/结论）。")
    summary = chat(reflect_prompt, system=build_system())
    entry = memory.add_memory(f"复盘（问题：{question[:40]}）：{summary}")
    print(f"\n[记忆] 已存入长期记忆（编号 {entry['id']}）：{summary}")


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    clear = "--clear" in args
    args = [a for a in args if a != "--clear"]
    QUESTION = (args[0] if args
                else "找一篇关于锂离子电池寿命预测的论文，记住它的标题和 DOI。")
    if clear:
        print(memory.clear_memory())
    print(f"问题：{QUESTION}")
    if "清空" in QUESTION and "记忆" in QUESTION:
        print(memory.clear_memory())
    else:
        run(QUESTION)