# -*- coding: utf-8 -*-
"""人在回路（Human-in-the-Loop）模块 —— 独立数据层，不依赖主流程。

作用：把「人工反馈」变成评审/生成器可消费的结构化输入，实现赛题能力项
（四）「智能体思辨与人在回路」：人对假设提问/质疑/修改，反馈回灌下一轮迭代。

设计要点：
- 本文件只做数据模型 + 格式化 + 存取，可独立测试；
- 合入主流程后，langgraph_agent.py 只需在 3 个点消费本模块：
  ① state 初始化加 human_feedback 字段
  ② review_hypothesis 的 user prompt 注入 format_feedback_for_review()
  ③ hypothesis_gen 的 prompt 注入 format_feedback_for_generator()
- 前端/API 通过 save_feedback / load_feedback 读写 feedback.json，与流程解耦。
"""
import json
import os
import sys
import io
import time

FEEDBACK_FILE = "feedback.json"

VERDICTS = ("通过", "质疑", "修改", "未评价")


def empty_feedback():
    """新建一条空反馈（人工未操作时的默认形态）。"""
    return {
        "verdict": "未评价",
        "score_opinion": None,
        "questions": [],
        "suggestions": [],
        "priority": "normal",
        "author": "user",
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "open",
    }


def feedback_path(run_folder):
    return os.path.join(run_folder, FEEDBACK_FILE)


def load_feedback(run_folder):
    """读运行文件夹里的 feedback.json；不存在返回 None（表示无人工反馈）。"""
    fp = feedback_path(run_folder)
    if not os.path.isfile(fp):
        return None
    try:
        with io.open(fp, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    if isinstance(data, list):
        data = data[-1] if data else None
    return data if isinstance(data, dict) else None


def save_feedback(run_folder, feedback):
    """写入 feedback.json（追加进历史列表，保留多轮人工反馈轨迹）。"""
    os.makedirs(run_folder, exist_ok=True)
    fb = dict(feedback)
    fb.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S"))
    fb.setdefault("status", "open")
    fp = feedback_path(run_folder)
    history = []
    if os.path.isfile(fp):
        try:
            with io.open(fp, "r", encoding="utf-8") as f:
                old = json.load(f)
            history = old if isinstance(old, list) else ([old] if isinstance(old, dict) else [])
        except Exception:
            history = []
    history.append(fb)
    with io.open(fp, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    return fp


def format_feedback_for_review(fb):
    """评审提示词注入段：人工反馈是最优先级信号。

    规则：评审必须先核对人工反馈——人工质疑的点必须正面回应，
    人工建议必须逐条给出采纳/不采纳及理由；评分不得无视人工意见。
    """
    if not fb or fb.get("verdict") == "未评价":
        return "（无人工反馈）"
    lines = ["【人工反馈（优先级最高，必须逐条回应）】"]
    lines.append(f"- 判定：{fb.get('verdict', '未评价')}")
    if fb.get("score_opinion") is not None:
        lines.append(f"- 分数意见：{fb['score_opinion']}")
    qs = fb.get("questions") or []
    if qs:
        lines.append("- 人工疑问（必须逐条回答）：")
        for i, q in enumerate(qs, 1):
            lines.append(f"  {i}. {q}")
    ss = fb.get("suggestions") or []
    if ss:
        lines.append("- 人工建议（逐条给出采纳/不采纳+理由）：")
        for i, s in enumerate(ss, 1):
            lines.append(f"  {i}. {s}")
    return "\n".join(lines)


def format_feedback_for_generator(fb):
    """生成器/修订提示词注入段：修改假设时必须优先落实人工建议。"""
    if not fb or fb.get("verdict") == "未评价":
        return "（无人工反馈）"
    lines = ["【人工反馈（修改假设时优先满足，无法满足须说明原因）】"]
    lines.append(f"- 判定：{fb.get('verdict', '未评价')}")
    ss = fb.get("suggestions") or []
    if ss:
        lines.append("- 必须落实的修改建议：")
        for i, s in enumerate(ss, 1):
            lines.append(f"  {i}. {s}")
    qs = fb.get("questions") or []
    if qs:
        lines.append("- 需要澄清的疑问：")
        for i, q in enumerate(qs, 1):
            lines.append(f"  {i}. {q}")
    return "\n".join(lines)


def summarize_feedback(fb):
    """给日志/折线图用的简短摘要。"""
    if not fb:
        return "无"
    return f"{fb.get('verdict', '?')}（疑问{len(fb.get('questions') or [])}条/建议{len(fb.get('suggestions') or [])}条）"


def cli_add(run_folder):
    """命令行交互添加反馈：python human_loop.py add <run_folder>"""
    fb = empty_feedback()
    print("=== 人工反馈录入（回车跳过=不填）===")
    v = input("判定（通过/质疑/修改）：").strip()
    if v in VERDICTS:
        fb["verdict"] = v
    while True:
        q = input("疑问（回车结束）：").strip()
        if not q:
            break
        fb["questions"].append(q)
    while True:
        s = input("修改建议（回车结束）：").strip()
        if not s:
            break
        fb["suggestions"].append(s)
    p = input("优先级（high/normal/low，回车=normal）：").strip()
    if p in ("high", "normal", "low"):
        fb["priority"] = p
    fp = save_feedback(run_folder, fb)
    print(f"已保存：{fp}")
    print("--- 评审侧注入预览 ---")
    print(format_feedback_for_review(fb))


def cli_show(run_folder):
    fb = load_feedback(run_folder)
    if fb is None:
        print("该运行无人工反馈记录")
        return
    print(json.dumps(fb, ensure_ascii=False, indent=2))


def main():
    if len(sys.argv) < 3:
        print("用法：")
        print("  python human_loop.py add <运行文件夹>   # 交互式录入人工反馈")
        print("  python human_loop.py show <运行文件夹>  # 查看已有反馈")
        return
    cmd, folder = sys.argv[1], sys.argv[2]
    if cmd == "add":
        cli_add(folder)
    elif cmd == "show":
        cli_show(folder)
    else:
        print(f"未知命令：{cmd}")


if __name__ == "__main__":
    main()
