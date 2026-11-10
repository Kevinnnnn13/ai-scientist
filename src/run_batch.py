# -*- coding: utf-8 -*-
"""run_batch.py：批量跑题（为 125 题批量验证做准备）
用法：
  python run_batch.py q1.txt           # q1.txt 每行一道题，UTF-8
  python run_batch.py "题目1" "题目2"   # 直接传多道题
可选：
  --quality 超好          # 目标档位（默认 好=80）
  --label 批次名           # 输出日志文件名前缀
每道题独立跑，产出 logs/<label>_NN_<主题>.log，互不影响，一道挂了不阻塞后续。
"""
import os, subprocess, sys, time, io

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)))
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
        if a in ("--quality", "--label"):
            skip_next = True
            continue
        if a.startswith("--"):
            continue
        if os.path.isfile(a):
            with io.open(a, "r", encoding="utf-8-sig") as f:
                qs += [ln.strip() for ln in f if ln.strip()]
        else:
            qs.append(a)
    return qs

def main():
    args = sys.argv[1:]
    quality = "好"
    label = "batch"
    for i, a in enumerate(args):
        if a == "--quality" and i + 1 < len(args):
            quality = args[i + 1]
        elif a == "--label" and i + 1 < len(args):
            label = args[i + 1]
    qs = read_questions(args)
    if not qs:
        print("没有题目。用法：python run_batch.py q1.txt 或 python run_batch.py \"题目1\" \"题目2\"")
        sys.exit(1)
    log_dir = os.path.join(SRC, "logs")
    os.makedirs(log_dir, exist_ok=True)
    print(f"== 共 {len(qs)} 题，目标 {quality} 档，日志目录 {log_dir} ==")
    results = []
    for i, q in enumerate(qs, 1):
        topic = q[:20].replace("/", "_").replace("\\", "_").replace(":", "_").replace("?", "_").replace("*", "_").replace("|", "_").replace("<", "_").replace(">", "_").replace('"', "_").strip(" .")
        log = os.path.join(log_dir, f"{label}_{i:02d}_{topic}.log")
        safe_print(f"\n[{i}/{len(qs)}] 开始：{q[:40]}...")
        t0 = time.time()
        with io.open(log, "w", encoding="utf-8") as f:
            f.write(f"题目：{q}\n目标：{quality}\n开始：{time.strftime('%H:%M:%S')}\n\n")
            child_env = dict(os.environ)
            child_env["PYTHONIOENCODING"] = "utf-8"
            proc = subprocess.Popen(
                [PY, os.path.join(SRC, "langgraph_agent.py"), q, "--quality", quality],
                cwd=os.path.dirname(SRC), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", env=child_env,
            )
            for line in proc.stdout:
                f.write(line)
                safe_print("  " + line.rstrip()[-120:])
            proc.wait()
            dt = time.time() - t0
            f.write(f"\n结束：{time.strftime('%H:%M:%S')}（耗时 {dt:.0f}s）退出码 {proc.returncode}\n")
        ok = "✅" if proc.returncode == 0 else "❌"
        results.append((i, q[:40], ok, f"{dt:.0f}s", os.path.basename(log)))
        safe_print(f"[{i}/{len(qs)}] {ok} 耗时 {dt:.0f}s")
    safe_print("\n== 汇总 ==")
    for r in results:
        safe_print(f"  {r[0]:>2}. {r[1]}  {r[2]}  {r[3]}  -> {r[4]}")

if __name__ == "__main__":
    main()
