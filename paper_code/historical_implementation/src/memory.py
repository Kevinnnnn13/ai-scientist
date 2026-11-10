"""memory.py：Agent 的"长期记忆" —— 一个最简单的记忆库（JSON 文件版）

为什么需要它？
  之前的 react_agent.py 每次运行都是"失忆"的：
  跑完一次，对话历史就丢光了，下次运行什么也不记得，
  就像一个只做单次任务的临时工，做完就忘。

  记忆分两种，别混：
  - 短期记忆 = 一次运行内，Thought / Action / Observation 的对话历史
    （react_agent.py 里已经有，靠 history 列表）
  - 长期记忆 = 程序关掉、明天再打开，还记着的东西（今天新增）

怎么实现长期记忆？
  用最简单的方式：一个 JSON 文件（agent_memory.json）。
  - 要记的东西 -> 追加进文件（程序结束，记忆还留在磁盘上）
  - 要回忆的东西 -> 从文件里读回来
  这就是计算机里的"持久化"（persistence）：数据活到程序之外。

文件长这样（一个列表，每条是一条记忆）：
  {
    "entries": [
      {
        "id": 1,
        "time": "2026-08-06 09:00",
        "content": "Severson 2019 是电池寿命预测的经典论文",
        "tags": ["电池", "论文"]
      }
    ]
  }

本文件提供 5 个函数（后面 tools 和 react_agent 都会用到）：
  load_memory()      读记忆文件 -> 返回记忆列表
  save_memory(list)  把记忆列表写回文件
  add_memory(text)   追加一条新记忆（自动编号 + 盖时间戳 + 存盘）
  search_memory(kw)  按关键词搜索记忆
  recent_memory(n)   取最近 n 条记忆（拼进系统提示词用）
"""
import json
import os
import time

# 记忆文件放在"本文件所在目录"下（同步到桌面后就是 src\agent_memory.json）
# __file__ = 本文件路径，abspath 转绝对路径，dirname 取目录 -> 拼出完整文件路径
MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent_memory.json")


def load_memory():
    """读记忆文件 -> 返回记忆列表（entry 的 list）。
    文件不存在或坏了 -> 返回空列表（不让程序崩，和 call_tool 的容错同一个思路）。
    """
    if not os.path.exists(MEMORY_FILE):
        return []
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("entries", [])
    except (json.JSONDecodeError, OSError):
        return []


def save_memory(entries):
    """把记忆列表写回文件（indent=2 只是为了让人类打开文件时看得舒服）。"""
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"entries": entries}, f, ensure_ascii=False, indent=2)


def add_memory(content, tags=None):
    """追加一条新记忆并保存。

    content: 要记的内容（字符串）
    tags:    可选标签列表，方便以后分类，如 ["电池", "论文"]
    返回:    这条新记忆的字典（给调用方确认用）
    """
    entries = load_memory()
    new_entry = {
        "id": len(entries) + 1,
        "time": time.strftime("%Y-%m-%d %H:%M"),
        "content": content,
        "tags": tags or [],
    }
    entries.append(new_entry)
    save_memory(entries)
    return new_entry


def search_memory(keyword, limit=5):
    """按关键词搜索记忆，返回命中的列表（新的排前面）。

    keyword: 关键词（比如"电池"）
    limit:   最多返回几条，默认 5
    """
    keyword = keyword.strip().lower()
    if not keyword:
        return []
    hits = []
    for e in load_memory():
        text = e.get("content", "")
        tags = " ".join(e.get("tags", []))
        if keyword in text.lower() or keyword in tags.lower():
            hits.append(e)
    hits.sort(key=lambda e: e.get("id", 0), reverse=True)
    return hits[:limit]


def recent_memory(limit=5):
    """取最近 n 条记忆（按 id 倒序），给系统提示词注入用。"""
    entries = load_memory()
    entries.sort(key=lambda e: e.get("id", 0), reverse=True)
    return entries[:limit]

def clear_memory():
    """清空长期记忆：把记忆文件重置为空列表。"""
    save_memory([])
    return "已清空长期记忆（当前记忆条数：0）"


if __name__ == "__main__":
    # 自测：把记忆文件临时换成一个测试文件，测完删掉，不污染真实记忆
    MEMORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_memory_selftest.json")

    print("=== memory.py 自测 ===")
    add_memory("电池寿命预测经典论文 Severson 2019", ["电池"])
    add_memory("OpenAlex 是免费开放的论文数据库", ["工具"])

    print("最近 2 条记忆：")
    for e in recent_memory(2):
        print(" ", e["id"], e["time"], e["content"])

    print("搜索'电池'：")
    for e in search_memory("电池"):
        print(" ", e["content"])

    if os.path.exists(MEMORY_FILE):
        os.remove(MEMORY_FILE)
    print("自测完成，测试文件已清理")