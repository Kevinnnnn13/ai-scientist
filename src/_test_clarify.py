# -*- coding: utf-8 -*-
"""_test_clarify.py：追问精修闸门自测

用法：
  python src/_test_clarify.py        # 白名单/合并 离线测试（不联网）
  python src/_test_clarify.py --llm  # 加测 LLM 判断（联网）
"""
import os
import sys

os.environ.setdefault("SAFETY_GUARD_LLM", "0" if "--llm" not in sys.argv else "1")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import clarify  # noqa: E402

CASES = [
    # (名称, 问题, 论文, 预期是否需要追问)
    ("白名单-125题", "What makes prime numbers so special?", None, False),
    ("清晰-英文", "What causes the 11-year solar cycle?", None, False),
    ("清晰-中文", "钙钛矿太阳能电池的稳定性为什么难以提升？", None, False),
    ("模糊-大而空", "How to cure cancer?", None, True),
    ("模糊-指代不明", "Why does it happen and how can we fix it?", None, True),
    ("带论文-衔接", "Based on these papers, what should we do next?",
     ["This paper studies perovskite solar cell stability under humidity."], True),
]


def main():
    llm_on = "--llm" in sys.argv
    print("== 追问精修闸门自测（LLM 判断：%s）==\n" % ("开启" if llm_on else "关闭(仅白名单)"))
    passed = skipped = 0
    for name, q, papers, expect in CASES:
        if expect and not llm_on:
            print("  [跳过-需LLM] %-16s %s" % (name, q[:46]))
            skipped += 1
            continue
        r = clarify.needs_clarification(q, papers)
        ok = bool(r["need_clarify"]) == expect
        if ok:
            passed += 1
        print("  [%s] %-16s 追问=%-5s %s" % (
            "PASS" if ok else "FAIL", name, r["need_clarify"], r["reason"] or ""))
        if not ok:
            print("        期望=%s，实际=%s" % (expect, r["need_clarify"]))

    # 合并函数测试（离线可测）
    merged = clarify.merge_clarification(
        "How to cure cancer?",
        [{"question": "你关注哪种癌症？", "answer": "非小细胞肺癌"},
         {"question": "希望得到什么？", "answer": "机制解释与候选靶点"}])
    assert "How to cure cancer?" in merged and "非小细胞肺癌" in merged
    assert "1. 追问：你关注哪种癌症？" in merged
    assert "2. 追问：希望得到什么？" in merged
    assert "用户补充：机制解释与候选靶点" in merged
    print("\n  [PASS] merge_clarification 合并上下文（含 2 条 Q&A，原问题保留）")
    passed += 1

    print("\n结果：通过 %d / 跳过 %d" % (passed, skipped))
    return 0 if (passed + skipped) == len(CASES) + 1 else 1


if __name__ == "__main__":
    sys.exit(main())
