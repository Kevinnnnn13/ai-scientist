"""config.py：配置加载与预算分配 —— 让 news_digest 变成"配置驱动"

这个模块管两件事：
1. 读 config.json（load_config）
2. 把关键词权重换算成搜索预算（build_search_plan）

为什么单独一个文件？
—— news_digest.py 只需要 import 它，改配置永远只动 config.json，不动主流程代码。
"""
import json
import os

# 配置文件路径：__file__ 定位，保证在哪个目录运行都能找到
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # src/
CONFIG_PATH = os.path.join(BASE_DIR, "..", "config.json")   # 项目根目录


def load_config(path=CONFIG_PATH):
    """读取 config.json，返回字典。

    用 utf-8-sig 打开：自动跳过文件开头的 BOM（Windows 工具保存 UTF-8 常带 BOM，
    上次 config.json 的 JSONDecodeError 就是它）。
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        return json.load(f)


def allocate_budget(config, total_budget):
    """按权重分配预算，把取整丢掉的余量补给最后一个人。

    坑（昨天踩过）：直接 int() 截断会导致总和 < 总预算（7+3+1=11）。
    解法：先取整，再把差额补给最后一个关键词，总和恒等于总预算。
    """
    keywords = config["关键词"]
    total_weight = sum(k["权重"] for k in keywords)

    shares = []
    used = 0
    for k in keywords:
        share = int(total_budget * k["权重"] / total_weight)
        shares.append(share)
        used += share                       # 记下已分配的总数

    shares[-1] += total_budget - used       # 余量补最后

    return list(zip([k["词"] for k in keywords], shares))


def build_search_plan(config):
    """生成完整搜索计划：[(关键词, 搜索条数), ...]

    news_digest.py 只需要这一句，就能拿到"每个关键词搜几条"。
    """
    return allocate_budget(config, config["搜索总预算"])
