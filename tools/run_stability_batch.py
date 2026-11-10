# -*- coding: utf-8 -*-
"""稳定性测试批跑脚本：串行跑 N 题，每题结果隔离到独立 AI_LOG_DIR，与正式运行数据互不干扰。

用法：
  python tools/run_stability_batch.py tests/stest_q22.txt --quality 超好 --label stest_q22

输出：
  src/logs/stest_<时间戳>/_progress.json   进度（供外部轮询）
  src/logs/stest_<时间戳>/_summary.json   汇总（全部跑完后）
  src/logs/stest_<时间戳>/q<NN>/run.log   每题运行日志
  src/logs/stest_<时间戳>/q<NN>/运行NN/   langgraph_agent 产物（01/02/state.json 等）
"""
import json
import os
import subprocess
import sys
import time
import io

SRC = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
PROJ = os.path.normpath(os.path.join(SRC, ".."))
PY = sys.executable


def safe_print(s):
    try:
        print(s, flush=True)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((str(s) + "\n").encode("gbk", "replace"))
        sys.stdout.buffer.flush()


def read_questions(args):
    qs = []
    skip_next = False
    for a in args:
        if skip_next:
            skip_next = False
            continue
        if a in ("--quality", "--label", "--logdir"):
            skip_next = True
            continue
        if a.startswith("--"):
            continue
        if os.path.isfile(a):
            with io.open(a, "r", encoding="utf-8-sig") as f:
                qs += [ln.strip() for ln in f if ln.strip() and not ln.strip().startswith("#")]
        else:
            qs.append(a)
    return qs


def write_json(path, obj):
    try:
        with io.open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main():
    args = sys.argv[1:]
    quality = "超好"
    label = "stest"
    logdir = None
    for i, a in enumerate(args):
        if a == "--quality" and i + 1 < len(args):
            quality = args[i + 1]
        elif a == "--label" and i + 1 < len(args):
            label = args[i + 1]
        elif a == "--logdir" and i + 1 < len(args):
            logdir = args[i + 1]
    qs = read_questions(args)
    if not qs:
        print("没有题目。用法：python tools/run_stability_batch.py q.txt [--quality 超好] [--label xxx]")
        sys.exit(1)
    if not logdir:
        logdir = os.path.join(SRC, "logs", f"{label}_{time.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(logdir, exist_ok=True)

    progress = {"label": label, "quality": quality, "total": len(qs),
                "done": 0, "ok": 0, "fail": 0, "started": time.time(),
                "items": [], "current": None}
    safe_print(f"== 共 {len(qs)} 题，目标 {quality} 档，隔离日志目录 {logdir} ==")

    for i, q in enumerate(qs, 1):
        topic = q[:24].replace("/", "_").replace("\\", "_").replace(":", "_").replace("?", "_") \
            .replace("*", "_").replace("|", "_").replace("<", "_").replace(">", "_").replace('"', "_").strip(" .")
        qdir = os.path.join(logdir, f"q{i:02d}_{topic}")
        os.makedirs(qdir, exist_ok=True)
        run_log = os.path.join(qdir, "run.log")
        progress["current"] = {"no": i, "question": q[:60], "qdir": qdir, "started": time.time()}
        write_json(os.path.join(logdir, "_progress.json"), progress)
        safe_print(f"\n[{i}/{len(qs)}] 开始：{q[:50]}...")
        t0 = time.time()
        child_env = dict(os.environ)
        child_env["PYTHONIOENCODING"] = "utf-8"
        child_env["AI_LOG_DIR"] = qdir  # 每题独立结果目录，避免序号竞争
        proc = subprocess.Popen(
            [PY, os.path.join(SRC, "langgraph_agent.py"), q, "--quality", quality],
            cwd=PROJ, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", env=child_env,
        )
        with io.open(run_log, "w", encoding="utf-8") as f:
            f.write(f"题目：{q}\n目标：{quality}\n开始：{time.strftime('%H:%M:%S')}\n\n")
            for line in proc.stdout:
                f.write(line)
                f.flush()
            proc.wait()
            dt = time.time() - t0
            f.write(f"\n结束：{time.strftime('%H:%M:%S')}（耗时 {dt:.0f}s）退出码 {proc.returncode}\n")
        ok = proc.returncode == 0
        # 尝试读取运行产物里的关键指标
        state = None
        folder = None
        for root, dirs, files in os.walk(qdir):
            if "state.json" in files:
                try:
                    with io.open(os.path.join(root, "state.json"), "r", encoding="utf-8") as f:
                        state = json.load(f)
                    folder = root
                    break
                except Exception:
                    pass
        item = {"no": i, "question": q, "ok": ok, "seconds": round(dt),
                "log": run_log, "exit_code": proc.returncode,
                "folder": folder, "best_score": None, "rounds": None,
                "error": None}
        if state:
            item["best_score"] = state.get("best_score")
            item["best_data_score"] = state.get("best_data_score")
            item["rounds"] = len(state.get("score_history") or [])
            item["cost_cny"] = state.get("api_cost_cny")
            item["api_usage"] = state.get("api_usage")
            if state.get("error"):
                item["error"] = str(state.get("error"))[:300]
        elif not ok:
            try:
                with io.open(run_log, "r", encoding="utf-8", errors="replace") as f:
                    tail = "\n".join(f.read().splitlines()[-8:])
                item["error"] = (tail or "(无日志)")[:300]
            except Exception:
                pass
        progress["items"].append(item)
        progress["done"] = i
        progress["ok"] += 1 if ok else 0
        progress["fail"] += 0 if ok else 1
        progress["current"] = None
        write_json(os.path.join(logdir, "_progress.json"), progress)
        safe_print(f"[{i}/{len(qs)}] {'OK' if ok else 'FAIL'} 耗时 {dt:.0f}s 分数 {item['best_score']}")

    progress["finished"] = time.time()
    write_json(os.path.join(logdir, "_summary.json"), progress)
    safe_print("\n== 汇总 ==")
    for it in progress["items"]:
        safe_print(f"  {it['no']:>2}. {'OK ' if it['ok'] else 'FAIL'} 分数={it['best_score']} 轮次={it['rounds']} {it['seconds']}s  {it['question'][:40]}")


if __name__ == "__main__":
    main()
