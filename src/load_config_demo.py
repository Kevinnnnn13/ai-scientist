"""load_config_demo.py：config.json 读取演示 —— 新闻 Digest 平台"配置驱动"第一步

这个文件做什么：
1. 从 config.json 读配置（领域、关键词+权重、预算等）
2. 演示"权重 -> 搜索预算"的分配算法
3. 打印结果，让你直观看到"配置是怎么被代码消费的"

用法：
    python src/load_config_demo.py
"""
import json
import os

# 配置文件路径：用 __file__ 定位，这样无论你在哪个目录运行都能找到 config.json
BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # 本文件所在目录 = src/
CONFIG_PATH = os.path.join(BASE_DIR, "..", "config.json")   # 上一级 = 项目根目录


def load_config(path=CONFIG_PATH):
    """读取 config.json，返回一个字典（dict）。

    为什么单独抽一个函数？
    —— 以后 news_digest.py 只需要调用 load_config() 就能拿到全部配置，
       改配置只动 config.json、不动代码。这就是"配置驱动"的核心。
    """
    with open(path, "r", encoding="utf-8-sig") as f:
        config = json.load(f)      # JSON 文本 -> Python 字典
    return config


def allocate_budget(config, total_budget):
    """按权重分配预算，并把取整丢掉的余量补给最后一个人。

    为什么这么写？
    —— 直接 int() 截断会导致总和 < 总预算（比如 7+3+1=11）。
       先取整，再把差额补给最后一个，总和就恒等于 12。
    """
    keywords = config["关键词"]
    total_weight = sum(k["权重"] for k in keywords)

    # 第一步：每个人先拿整数部分（int 截断小数）
    shares = []
    used = 0
    for k in keywords:
        share = int(total_budget * k["权重"] / total_weight)
        shares.append(share)
        used += share                       # 记录已经分出去多少

    # 第二步：把余量补给最后一个人（总预算 - 已分配 = 丢掉的差额）
    shares[-1] += total_budget - used

    # 把"词"和"条数"配对返回：[(词, 条数), ...]
    return list(zip([k["词"] for k in keywords], shares))
def main():
    """主流程：读配置 -> 分配预算 -> 打印（三行代码，各干一件事）"""
    config = load_config()

    print("=== 读到的配置 ===")
    print(f"领域：{config['领域']}")
    for k in config["关键词"]:
        print(f"  关键词：{k['词']}（权重 {k['权重']}）")
    print(f"搜索总预算：{config['搜索总预算']} 条")

    print("\n=== 权重 -> 预算分配 ===")
    for word, count in allocate_budget(config, config["搜索总预算"]):
        print(f"  '{word}' 搜 {count} 条")


if __name__ == "__main__":
    main()
