# -*- coding: utf-8 -*-
"""批量生成 12 字段《科学假设与研究计划》（04_研究计划.md）。

用法：
  python src/gen_plans_batch.py                          # 扫全部运行文件夹，只补缺的
  python src/gen_plans_batch.py --force                  # 已有也重新生成
  python src/gen_plans_batch.py --limit 10               # 只处理前 N 个（试跑）
  python src/gen_plans_batch.py --only 79 80 145         # 只处理指定运行号

说明：
- 只读各运行文件夹的 state.json，调用 langgraph_agent.generate_plan_from_folder
  生成 04_研究计划.md（会调用一次 LLM，每题约 1-2 分钟）。
- 不会修改 langgraph_agent.py / run_batch.py，不影响正在跑的批处理。
"""
import os
import sys
import io
import time

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)

LOG_BASE = r"C:\Users\22011\Desktop\26暑假\27日\生成日志"


def find_run_folders(only=None):
    """扫全部运行文件夹（兼容根目录 + 日期子目录两种布局），只认目录，忽略 .md 等文件。"""
    folders = []
    import re

    def scan(root):
        for name in sorted(os.listdir(root)):
            if not name.startswith("运行"):
                continue
            full = os.path.join(root, name)
            if not os.path.isdir(full):
                continue  # 跳过早期的单文件日志（运行01_xxx.md）
            m = re.match(r"运行(\d+)", name)
            rid = int(m.group(1)) if m else None
            if only and rid not in only:
                continue
            folders.append((rid, full))

    scan(LOG_BASE)  # 根目录直接放运行文件夹的情况（运行146+）
    for day in sorted(os.listdir(LOG_BASE)):
        daydir = os.path.join(LOG_BASE, day)
        if not os.path.isdir(daydir):
            continue
        if day.startswith("运行"):
            continue
        scan(daydir)
    folders.sort(key=lambda x: (x[0] is None, x[0] or 0))
    return folders


def main():
    args = sys.argv[1:]
    force = "--force" in args
    limit = None
    only = None
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
    if "--only" in args:
        i = args.index("--only")
        only = set(int(x) for x in args[i + 1:])

    from langgraph_agent import generate_plan_from_folder

    folders = find_run_folders(only)
    if limit:
        folders = folders[:limit]
    print(f"共 {len(folders)} 个运行文件夹待处理（force={force}）")
    ok, skip, fail = 0, 0, 0
    fails = []
    t0 = time.time()
    for i, (rid, folder) in enumerate(folders, 1):
        plan_path = os.path.join(folder, "04_研究计划.md")
        if os.path.isfile(plan_path) and not force:
            skip += 1
            print(f"[{i}/{len(folders)}] 跳过（已有）运行{rid}")
            continue
        try:
            p, text = generate_plan_from_folder(folder)
            if p:
                ok += 1
                print(f"[{i}/{len(folders)}] OK 运行{rid} -> {os.path.basename(p)}")
            else:
                fail += 1
                fails.append((rid, str(text)[:100]))
                print(f"[{i}/{len(folders)}] FAIL 运行{rid}: {str(text)[:100]}")
        except Exception as e:
            fail += 1
            fails.append((rid, str(e)[:100]))
            print(f"[{i}/{len(folders)}] EXC 运行{rid}: {str(e)[:100]}")
    dt = time.time() - t0
    print(f"\n完成：成功 {ok}，跳过 {skip}，失败 {fail}，耗时 {dt:.0f}s")
    if fails:
        print("失败明细：")
        for rid, msg in fails:
            print(f"  运行{rid}: {msg}")


if __name__ == "__main__":
    main()
