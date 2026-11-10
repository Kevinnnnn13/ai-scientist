# -*- coding: utf-8 -*-
"""补跑实时监控：看进度、看异常、看 0 分迹象。

用法：python src/run_monitor.py
输出：当前进度（N/60）、最近完成的题、最新日志是否有报错/0分迹象。
"""
import os
import re
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import glob
import time

SRC = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SRC, "logs")
BATCH_FILE = r"C:\Users\22011\Desktop\26暑假\ai_scientist\batch_s125_resume_20260809.txt"
LABEL = "s125_full_20260809b"


def tail(path, n=30):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        return lines[-n:]
    except Exception:
        return []


def main():
    now = time.strftime("%H:%M:%S")
    print(f"==== 补跑监控 {now} ====")
    if not os.path.isfile(BATCH_FILE):
        print("找不到批处理输出文件（可能还没开始写）")
        return
    size = os.path.getsize(BATCH_FILE)
    mt = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(BATCH_FILE)))
    print(f"批处理文件：{size/1024:.0f} KB，最后写入 {mt}")
    lines = tail(BATCH_FILE, 60)
    # 找 [N/60] 开始 / 结束 行
    starts = [l for l in lines if re.search(r"\[\d+/60\] 开始", l)]
    ends = [l for l in lines if re.search(r"\[\d+/60\] 结束|耗时", l)]
    for l in starts:
        print("  ", l.rstrip()[:90])
    # 最新日志文件：找最新一个 s125_full_20260809b_*.log
    logs = sorted(glob.glob(os.path.join(LOG_DIR, LABEL + "_*.log")), key=os.path.getmtime)
    if logs:
        latest = logs[-1]
        lm = time.strftime("%H:%M:%S", time.localtime(os.path.getmtime(latest)))
        print(f"最新日志：{os.path.basename(latest)}（{lm}，{os.path.getsize(latest)/1024:.0f} KB）")
        lt = tail(latest, 40)
        joined = "\n".join(lt)
        # 异常检测
        bad = []
        if re.search(r"Traceback|OSError|Errno|RecursionError", joined):
            bad.append("发现 Traceback/OSError")
        if re.search(r"假设分=0|hypothesis_score.*0|数据分=0", joined):
            bad.append("发现 0 分迹象")
        if re.search(r"429|Too Many Requests|timeout|Timeout", joined):
            bad.append("发现 429/超时迹象")
        if bad:
            print("⚠️ " + "；".join(bad))
            for l in lt[-12:]:
                print("   ", l.rstrip()[:110])
        else:
            print("无异常迹象")
            for l in lt[-6:]:
                print("   ", l.rstrip()[:110])
    else:
        print("还没有补跑日志（可能刚开始）")


if __name__ == "__main__":
    main()
