# -*- coding: utf-8 -*-
"""只跑发散通道（temperature=0.5 头脑风暴），不跑完整假设流程。

用法：
  python src\run_divergent.py "你的科学问题"
  python src\run_divergent.py "问题" --papers "文献1; 文献2"
输出：控制台打印 + 保存到 发散通道_<时间戳>.md（ai_scientist 目录下）
"""
import argparse
import io
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)

import langgraph_agent


def main():
    ap = argparse.ArgumentParser(description="只跑发散通道（temperature=0.5）")
    ap.add_argument("question", help="科学问题（作为研究缺口输入）")
    ap.add_argument("--papers", default="", help="可选：相关文献，分号分隔")
    ap.add_argument("--out", default="", help="输出 md 路径（默认 ai_scientist 目录下）")
    args = ap.parse_args()

    gap = "研究问题/缺口：" + args.question.strip()
    papers = args.papers.strip()
    print("== 发散通道（temperature=0.5）==")
    print("问题：", args.question)
    if papers:
        print("文献上下文：", papers[:200])
    print("-" * 60)
    out = langgraph_agent._divergent_candidate(gap, papers, "", "")
    if not out:
        print("发散通道没有产出（可能调用失败），请检查网络/代理。")
        sys.exit(1)
    print("\n" + "=" * 60)
    print("发散候选：\n" + out)

    path = args.out or os.path.join(os.path.dirname(SRC), "发散通道_%s.md" % time.strftime("%Y%m%d_%H%M%S"))
    with io.open(path, "w", encoding="utf-8") as f:
        f.write("# 发散通道输出（temperature=0.5）\n\n")
        f.write("- **问题**：%s\n" % args.question)
        if papers:
            f.write("- **文献上下文**：%s\n" % papers)
        f.write("- **生成时间**：%s\n\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        f.write("## 发散候选\n\n%s\n" % out)
    print("\n已保存：%s" % path)


if __name__ == "__main__":
    main()