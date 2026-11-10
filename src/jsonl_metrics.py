# -*- coding: utf-8 -*-
"""jsonl_metrics.py：L5 评审 JSONL 三指标聚合 + 字段断言（批次 C 验收用）。

用法：
  python src/jsonl_metrics.py                    # 扫全部运行文件夹
  python src/jsonl_metrics.py <运行文件夹>         # 只看单个文件夹
  python src/jsonl_metrics.py --min-runs 3       # 分数方差至少 N 次运行同题

产出：
  1. 字段断言：每行必含 body_hash / tree_version / divergence（无探测为 null）
  2. 分数方差：同一题目多次运行、同轮次 hypothesis_score 的 std（需 >=3 次运行）
  3. 要点一致性：多次运行 points name 集合的 Jaccard
  4. 意见重合度：相邻轮 reasons 文本相似度；>0.8 且分数未变 -> 平台期事件计数
"""
import difflib
import io
import json
import os
import re
import statistics
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOG_BASE = r"C:\Users\22011\Desktop\26暑假\27日\生成日志"


def find_run_folders(root):
    folders = []

    def scan(d):
        for name in sorted(os.listdir(d)):
            full = os.path.join(d, name)
            if not os.path.isdir(full):
                continue
            if re.match(r"运行\d+", name):
                folders.append(full)
            else:
                scan(full)

    if os.path.isdir(root):
        scan(root)
    return folders


def load_jsonl(folder):
    path = os.path.join(folder, "03_评审JSONL.jsonl")
    if not os.path.isfile(path):
        return None, []
    rows = []
    with io.open(path, "r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                rows.append(None)
    return path, rows


def load_question(folder):
    sp = os.path.join(folder, "state.json")
    if os.path.isfile(sp):
        try:
            with io.open(sp, "r", encoding="utf-8") as f:
                return (json.load(f) or {}).get("question", "")
        except Exception:
            return ""
    return ""


def main():
    args = sys.argv[1:]
    min_runs = 3
    if "--min-runs" in args:
        i = args.index("--min-runs")
        min_runs = int(args[i + 1])
    targets = [a for a in args if not a.startswith("--") and a != args[args.index("--min-runs") + 1] if "--min-runs" in args] if "--min-runs" in args else [a for a in args if not a.startswith("--")]
    if targets:
        folders = [t for t in targets if os.path.isdir(t)]
    else:
        folders = find_run_folders(LOG_BASE)

    print(f"扫描到 {len(folders)} 个运行文件夹")
    missing = []
    by_question = {}
    plat_events = 0
    plat_runs = 0
    field_bad = []
    total_rows = 0
    for folder in folders:
        path, rows = load_jsonl(folder)
        if path is None:
            missing.append(os.path.basename(folder))
            continue
        q = load_question(folder)
        valid = [r for r in rows if r is not None]
        total_rows += len(valid)
        # 字段断言
        for i, r in enumerate(valid, 1):
            for fld in ("body_hash", "tree_version", "divergence"):
                if fld not in r.get("input", {}) and fld != "divergence":
                    field_bad.append((os.path.basename(folder), i, fld))
                if fld == "divergence" and fld not in r:
                    field_bad.append((os.path.basename(folder), i, fld))
            if "body_hash" not in r.get("input", {}):
                field_bad.append((os.path.basename(folder), i, "input.body_hash"))
            if "tree_version" not in r:
                field_bad.append((os.path.basename(folder), i, "tree_version"))
            if "divergence" not in r:
                field_bad.append((os.path.basename(folder), i, "divergence"))
        # 意见重合度（同一 run 内相邻轮）
        prev_text = None
        prev_score = None
        run_plat = 0
        for r in valid:
            reasons = r.get("output", {}).get("reasons") or []
            text = " ".join(str(x.get("issue", "")) for x in reasons if isinstance(x, dict))
            score = r.get("hypothesis_score")
            if prev_text and text:
                sim = difflib.SequenceMatcher(None, prev_text, text).ratio()
                if sim > 0.8 and prev_score is not None and score == prev_score:
                    run_plat += 1
            prev_text, prev_score = text, score
        if run_plat:
            plat_runs += 1
            plat_events += run_plat
        by_question.setdefault(q, []).append((os.path.basename(folder), valid))

    print(f"\n== 1) 字段断言 ==")
    if field_bad:
        print(f"  FAIL {len(field_bad)} 处缺字段：")
        for f, i, k in field_bad[:20]:
            print(f"    {f} 行{i}: 缺 {k}")
    else:
        print(f"  PASS：{total_rows} 行全部含 body_hash / tree_version / divergence")

    print(f"\n== 2) 分数方差（同题同轮次，需 >= {min_runs} 次运行）==")
    n_scores = 0
    for q, runs in sorted(by_question.items()):
        if len(runs) < min_runs:
            continue
        by_round = {}
        for name, rows in runs:
            for r in rows:
                rnd = r.get("round")
                sc = r.get("hypothesis_score")
                if rnd is not None and sc is not None and r.get("data_score", 0) >= 60:
                    by_round.setdefault(rnd, []).append(sc)
        for rnd in sorted(by_round):
            vals = by_round[rnd]
            if len(vals) >= min_runs:
                sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
                n_scores += 1
                print(f"  题「{q[:30]}」第{rnd}轮: {vals} std={sd:.2f}")
    if not n_scores:
        print(f"  （没有同题达到 {min_runs} 次运行，跳过）")

    print(f"\n== 3) 要点一致性（同题 points name Jaccard）==")
    n_jac = 0
    for q, runs in sorted(by_question.items()):
        if len(runs) < 2:
            continue
        base = None
        for name, rows in runs:
            names = set()
            for r in rows:
                for p in (r.get("output", {}).get("points") or []):
                    if isinstance(p, dict) and p.get("name"):
                        names.add(str(p["name"]))
            if base is None:
                base = names
                continue
            union = base | names
            if union:
                j = len(base & names) / len(union)
                n_jac += 1
                print(f"  题「{q[:30]}」{name}: Jaccard={j:.2f}")
    if not n_jac:
        print("  （没有同题多运行，跳过）")

    print(f"\n== 4) 意见重合度 ==")
    print(f"  相邻轮 reasons 相似>0.8 且分数未变（平台期事件）: {plat_events} 次，分布在 {plat_runs} 个运行")

    if missing:
        print(f"\n[提示] {len(missing)} 个运行文件夹没有 03_评审JSONL.jsonl（批次 C 之前生成的）：{missing[:10]}")
    print("\n完成")


if __name__ == "__main__":
    main()