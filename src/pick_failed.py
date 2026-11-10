# -*- coding: utf-8 -*-
"""失败/未跑题自动挑拣：从 125 全量中挑出待补跑题目，生成批处理列表。

用法：
  python src/pick_failed.py                # 挑 未跑 + 0分 + <85 分
  python src/pick_failed.py --min 85       # 阈值默认 85（不含）
  python src/pick_failed.py --out xxx.txt  # 指定输出文件
  python src/pick_failed.py --dry          # 只打印不写文件

输出：batch_retry_YYYYMMDD.txt（每行一题），可直接喂 run_batch.py。
"""
import io
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from gen_125_report import collect_runs

ALL_125 = os.path.join(SRC, "s125_all.txt")


def load_all_questions():
    with io.open(ALL_125, "r", encoding="utf-8-sig") as f:
        return [ln.strip() for ln in f if ln.strip()]


def main():
    args = sys.argv[1:]
    threshold = 85
    out = None
    dry = "--dry" in args
    for i, a in enumerate(args):
        if a == "--min" and i + 1 < len(args):
            threshold = int(args[i + 1])
        elif a == "--out" and i + 1 < len(args):
            out = args[i + 1]
    if not out:
        out = os.path.join(os.path.dirname(SRC), "batch_retry_%s.txt" % time.strftime("%Y%m%d"))

    all_q = load_all_questions()
    runs = {r["question"]: r for r in collect_runs()}

    missing, zero, low = [], [], []
    for q in all_q:
        r = runs.get(q)
        if r is None:
            missing.append(q)
        elif r["best"] == 0:
            zero.append(q)
        elif 0 < r["best"] < threshold:
            low.append(q)

    extra = [q for q in runs if q not in set(all_q)]

    lines = missing + zero + low

    print("=" * 60)
    print("125 题总数：%d · 已跑 %d · 未跑 %d" % (len(all_q), len(all_q) - len(missing), len(missing)))
    print("0 分（网络失败）：%d · <%d 低分：%d · 待补跑合计：%d" % (len(zero), threshold, len(low), len(lines)))
    if missing:
        print("\n[未跑]")
        for q in missing:
            print("  -", q)
    if zero:
        print("\n[0分-网络失败]")
        for q in zero:
            print("  -", q)
    if low:
        print("\n[<%d 低分]" % threshold)
        for q in low:
            print("  -", q)
    if extra:
        print("\n[日志中有但不在125列表（旧测试题）]")
        for q in extra:
            print("  -", q)
    if dry or not lines:
        print("\n（--dry 或无需补跑，未写文件）")
        return
    with io.open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print("\n已写入：%s" % out)


if __name__ == "__main__":
    main()