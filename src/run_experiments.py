# -*- coding: utf-8 -*-
"""参数优化实验框架：批量跑「题目 × 参数变体」并自动记录结果（挂机用）。

用法：
  1) 编辑 experiments.json（题目、档位、变体参数、是否加 --consumer 等）
  2) python src\run_experiments.py               # 顺序跑，结果写 experiments\results.csv
     python src\run_experiments.py --limit 2     # 只跑前 2 个
     python src\run_experiments.py --retry-fail  # 只重跑失败的

变体参数（每个变体 = 一组环境变量 + 附加参数）：
  {"name": "temp0", "env": {"REVIEW_TEMPERATURE": "0"}, "args": []}
环境变量按名注入；args 追加到 langgraph_agent.py 命令行。
"""
import csv
import io
import json
import os
import re
import sys
import time
import subprocess

SRC = os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(SRC, "langgraph_agent.py")
CFG = os.path.join(SRC, "experiments.json")
OUT_DIR = os.path.join(SRC, "..", "experiments")
CSV = os.path.join(OUT_DIR, "results.csv")

DEFAULT_CFG = {
    "questions": [
        {"question": "What makes prime numbers so special?", "quality": "超好"},
        {"question": "What is the microscopic mechanism for high-temperature superconductivity?", "quality": "超好"},
    ],
    "variants": [
        {"name": "baseline", "env": {}, "args": []},
        {"name": "temp0", "env": {"REVIEW_TEMPERATURE": "0"}, "args": []},
    ],
}


def ensure_cfg():
    if not os.path.isfile(CFG):
        with io.open(CFG, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CFG, f, ensure_ascii=False, indent=2)
        print("已创建默认实验配置：", CFG, "（请按需编辑）")
        return DEFAULT_CFG
    with io.open(CFG, "r", encoding="utf-8") as f:
        return json.load(f)


def run_one(question, quality, variant, tag):
    """跑一个 (题, 变体)，返回结果 dict。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(variant.get("env") or {})
    args = [sys.executable, AGENT, question, "--quality", quality] + (variant.get("args") or [])
    t0 = time.time()
    try:
        proc = subprocess.run(args, cwd=os.path.dirname(SRC), capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              env=env, timeout=3600)
        out = (proc.stdout or "") + (proc.stderr or "")
    except Exception as e:
        return {"tag": tag, "ok": False, "error": str(e)[:120], "seconds": round(time.time() - t0, 1)}
    # 从输出抠分数（langgraph_agent 打印「历史最高分：X（数据分 Y）」）
    m = re.search(r"历史最高分：(\d+)\s*（数据分\s*(\d+)）", out)
    m2 = re.search(r"\[图表\] 分数迭代曲线已保存", out)
    return {
        "tag": tag, "ok": proc.returncode == 0,
        "best": int(m.group(1)) if m else None,
        "data": int(m.group(2)) if m else None,
        "chart": bool(m2),
        "seconds": round(time.time() - t0, 1),
        "error": "" if proc.returncode == 0 else (out[-300:] if out else "无输出"),
    }


def load_done():
    rows = []
    if os.path.isfile(CSV):
        with io.open(CSV, "r", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    return rows


def main():
    args = sys.argv[1:]
    limit = None
    retry = "--retry-fail" in args
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])
    cfg = ensure_cfg()
    os.makedirs(OUT_DIR, exist_ok=True)
    tasks = []
    for v in cfg["variants"]:
        for q in cfg["questions"]:
            tag = f"{v['name']}|{q['question'][:24]}"
            tasks.append((q, v, tag))
    if limit:
        tasks = tasks[:limit]
    if retry:
        done_tags = {r["tag"] for r in load_done() if r.get("ok") == "True" or r.get("best")}
        tasks = [t for t in tasks if t[2] not in done_tags]
    print(f"共 {len(tasks)} 个任务（retry={retry}）")
    t0 = time.time()
    for i, (q, v, tag) in enumerate(tasks, 1):
        print(f"[{i}/{len(tasks)}] {tag} ...", flush=True)
        res = run_one(q["question"], q["quality"], v, tag)
        res.update({"question": q["question"], "quality": q["quality"], "variant": v["name"],
                    "ts": time.strftime("%Y-%m-%d %H:%M:%S")})
        # 追加 CSV
        new = not os.path.isfile(CSV)
        with io.open(CSV, "a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["tag", "question", "quality", "variant", "best", "data",
                                              "chart", "seconds", "ok", "error", "ts"])
            if new:
                w.writeheader()
            w.writerow(res)
        print(f"    -> {res.get('best')} / data {res.get('data')} ({res.get('seconds')}s) {res.get('error', '')[:80]}", flush=True)
    print(f"完成，结果在 {CSV}，总耗时 {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
