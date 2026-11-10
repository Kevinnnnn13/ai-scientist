# -*- coding: utf-8 -*-
"""补跑哨兵：自动检测批处理跑完 -> 自动执行三条后处理 -> 写完成标志。

用法：python src/watch_batch.py
- 监控 batch_s125_resume_20260810.txt，连续 90 秒无写入且出现 run_batch 完成标记
  （"== 汇总 =="）即判定跑完
- 跑完自动依次执行：gen_plans_batch.py（生成研究计划）-> gen_125_report.py（刷新文档）
  -> pick_failed.py（挑失败题）
- 全部完成后写 _补跑完成_<时间戳>.txt 到项目根目录，供 Codex 定时任务/你本人识别
- 若文件停止增长但未见完成标记，判定为中断，持续等待（不误触发）
"""
import io
import os
import subprocess
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SRC)
PY = sys.executable
BATCH = os.path.join(ROOT, "batch_s125_resume_20260810.txt")
STALL_ROUNDS = 3       # 连续 3 次（每次 30s）无写入 = 停止增长
CHECK_INTERVAL = 30
DONE_FLAG = os.path.join(ROOT, "_补跑完成_%s.txt" % time.strftime("%Y%m%d_%H%M%S"))


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)


def batch_size():
    try:
        return os.path.getsize(BATCH)
    except OSError:
        return -1


def has_done_marker():
    try:
        with io.open(BATCH, "r", encoding="utf-8", errors="replace") as f:
            tail = f.read()[-4000:]
        return ("== 汇总 ==" in tail) or ("全部" in tail and "完成" in tail)
    except OSError:
        return False


def run_step(name, args):
    log("开始执行：%s" % name)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen([PY] + args, cwd=ROOT, env=env)
    proc.wait()
    log("%s 结束，退出码 %s" % (name, proc.returncode))
    return proc.returncode == 0


def main():
    log("哨兵启动，监控：%s" % BATCH)
    log("补跑未结束前请勿关闭本窗口。")
    stall = 0
    last_size = None
    while True:
        size = batch_size()
        now = time.strftime("%H:%M:%S")
        if size < 0:
            log("批处理文件不存在，等待创建…")
        elif size != last_size:
            stall = 0
            log("批处理增长中（%d KB）" % (size // 1024))
        else:
            stall += 1
            log("无新写入（%d/%d 次）" % (stall, STALL_ROUNDS))
            if stall >= STALL_ROUNDS:
                if has_done_marker():
                    log("检测到完成标记，开始自动后处理…")
                    ok = True
                    ok = run_step("gen_plans_batch", [os.path.join(SRC, "gen_plans_batch.py")]) and ok
                    ok = run_step("gen_125_report", [os.path.join(SRC, "gen_125_report.py")]) and ok
                    ok = run_step("pick_failed", [os.path.join(SRC, "pick_failed.py")]) and ok
                    with io.open(DONE_FLAG, "w", encoding="utf-8") as f:
                        f.write("补跑后处理完成：%s\n研究计划/全量文档/失败题挑拣均已执行。\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
                    log("全部完成，标志文件：%s" % DONE_FLAG)
                    log("（若 batch_retry_*.txt 有内容，说明还有失败题需要补跑）")
                    return
                else:
                    log("文件停止增长但未见完成标记——疑似中断，继续等待，不触发后处理")
                    stall = 0  # 重置，防止误触发
        last_size = size
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()