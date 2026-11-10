# -*- coding: utf-8 -*-
"""运行总览汇总图：扫描 27日/生成日志，把每次运行的分数轨迹画进同一张图。
可重复运行：新跑完的批次会自动被扫进来（重新生成 PNG + 对照表 md）。
"""
import os, re, json, io, time
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
plt.rcParams["axes.unicode_minus"] = False

BASE = r"C:\Users\22011\Desktop\26暑假\27日\生成日志"
DAY_RE = re.compile(r"^2026-\d{2}-\d{2}$")

def parse_run_folder(folder):
    """state.json -> run dict"""
    sj = os.path.join(folder, "state.json")
    try:
        with io.open(sj, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:
        return None
    name = os.path.basename(folder)
    m = re.match(r"运行(\d+)", name)
    rid = int(m.group(1)) if m else None
    hist = st.get("score_history") or []
    if not hist:
        return None
    return {
        "id": rid, "question": st.get("question", ""), "target": st.get("quality_target", 90),
        "best": st.get("best_score", 0), "status": st.get("status", ""),
        "rounds": [(h.get("hypothesis_score", 0), h.get("data_score", 0)) for h in hist],
    }

def parse_0808_md(path):
    """08-08 总览 md 的分数迭代表 -> run dict"""
    try:
        txt = io.open(path, "r", encoding="utf-8").read()
    except Exception:
        return None
    m = re.search(r"运行(\d+)_总览", os.path.basename(path))
    rid = int(m.group(1)) if m else None
    qm = re.search(r"\*\*问题\*\*：(.+)", txt)
    tm = re.search(r"\*\*质量目标\*\*：(\d+)", txt)
    rows = re.findall(r"^\|\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*\|", txt, re.M)
    if not rows:
        return None
    rounds = [(int(h), int(d)) for (_, h, d) in rows]
    return {
        "id": rid, "question": qm.group(1).strip() if qm else "", "target": int(tm.group(1)) if tm else 90,
        "best": max(h for h, _ in rounds), "status": "",
        "rounds": rounds,
    }

def collect():
    """返回 [(day, runs), ...] 按日期升序；day 形如 '08-09'"""
    days = []
    for d in sorted(os.listdir(BASE)):
        fp = os.path.join(BASE, d)
        if os.path.isdir(fp) and DAY_RE.match(d):
            days.append(d)
    groups = []       # [(day, [runs])]
    nodata = []       # 顶层遗留：无 state 的运行文件夹（兼容旧格式）
    seen_all = set()
    for day in days:
        runs, nod = [], []
        daydir = os.path.join(BASE, day)
        for d in sorted(os.listdir(daydir)):
            fp = os.path.join(daydir, d)
            if not os.path.isdir(fp) or not re.match(r"运行\d+", d):
                continue
            r = parse_run_folder(fp)
            if r and r["id"] is not None:
                runs.append(r)
                seen_all.add(r["id"])
            else:
                m = re.match(r"运行(\d+)", d)
                if m:
                    nod.append({"id": int(m.group(1)), "question": d, "target": 90})
        # 08-08 的旧格式 md 兼容
        if day == "2026-08-08":
            for fn in sorted(os.listdir(daydir)):
                if fn.startswith("运行") and "_总览" in fn:
                    r = parse_0808_md(os.path.join(daydir, fn))
                    if r and r["id"] is not None:
                        old = next((x for x in runs if x["id"] == r["id"]), None)
                        if old is None or len(r["rounds"]) > len(old["rounds"]):
                            runs = [x for x in runs if x["id"] != r["id"]] + [r]
                            seen_all.add(r["id"])
        runs.sort(key=lambda r: r["id"])
        nod.sort(key=lambda r: r["id"])
        if runs or nod:
            groups.append((day, runs, nod))
    # 兼容：顶层未按日期归档的 运行NN 文件夹（按 id 合并，优先保留轮次多的）
    for d in sorted(os.listdir(BASE)):
        fp = os.path.join(BASE, d)
        if not os.path.isdir(fp) or not re.match(r"运行\d+_", d):
            continue
        r = parse_run_folder(fp)
        if not r or r["id"] in seen_all:
            continue
        if groups:
            groups[0][1].append(r)
        seen_all.add(r["id"])
    for _, runs, nod in groups:
        runs.sort(key=lambda r: r["id"])
        nod.sort(key=lambda r: r["id"])
    return groups

import numpy as np

def draw_heatmap(ax, runs, target, which, title):
    """热力图：每行=一次运行（按最高分降序），每格=该轮分数，颜色深浅=分数高低。"""
    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("#e8e8e8")
    runs_sorted = sorted(runs, key=lambda r: (-r["best"], r["id"]))
    ids = [r["id"] for r in runs_sorted]
    nrows = len(ids)
    data = np.full((nrows, 10), np.nan)
    for i, r in enumerate(runs_sorted):
        for j, (h, d) in enumerate(r["rounds"]):
            if j < 10:
                data[i, j] = h if which == "hyp" else d
    im = ax.imshow(data, cmap=cmap, vmin=0, vmax=100, aspect="auto",
                   extent=[0.5, 10.5, nrows - 0.5, -0.5])
    ax.set_yticks(range(nrows))
    ax.set_yticklabels([f"{rid}{'*' if rid in {x['id'] for x in runs if x['best'] >= target} else ''}" for rid in ids],
                       fontsize=6.5)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("轮次")
    ax.set_xticklabels(range(1, 11), fontsize=7)
    ax.grid(False)
    for x in range(11):
        ax.axvline(x + 0.5, color="white", lw=0.6)
    for y in range(nrows + 1):
        ax.axhline(y - 0.5, color="white", lw=0.6)
    passed = sum(1 for r in runs if r["best"] >= target)
    near = sum(1 for r in runs if target - 5 <= r["best"] < target)
    low = sum(1 for r in runs if r["best"] < target - 5)
    ax.set_title(f"{title}（达标 {passed} · 接近 {near} · 低分 {low}）", fontsize=10)
    return im

def main():
    groups = collect()
    if not groups:
        print("没有找到任何运行数据")
        return
    n_days = len(groups)
    # 布局：每天一行（假设分|数据分 两列）
    fig, axes = plt.subplots(n_days, 2, figsize=(18, max(6, 3.5 * n_days)), constrained_layout=True)
    if n_days == 1:
        axes = axes.reshape(1, 2)
    im1 = None
    for i, (day, runs, nod) in enumerate(groups):
        im1 = draw_heatmap(axes[i, 0], runs, 90, "hyp", f"{day} 假设分（每行=一次运行，绿=高红=低）")
        draw_heatmap(axes[i, 1], runs, 90, "data", f"{day} 数据分")
    fig.colorbar(im1, ax=axes, orientation="vertical", fraction=0.015, pad=0.02, label="分数 (0-100)")
    fig.suptitle("AI Scientist 运行总览热力图 · 一行=一次运行，一格=一轮分数（* = 达标）", fontsize=15, y=0.995)
    stamp = time.strftime("%Y%m%d")
    out_png = os.path.join(BASE, f"运行总览_热力图_{stamp}.png")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)

    # 对照表 md
    lines = ["# 运行对照表（运行号 → 题目）\n", "", "| 运行号 | 日期 | 目标 | 最高假设分 | 末轮数据分 | 轮次 | 状态 | 题目 |", "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    def row(r, day):
        rs = r["rounds"]
        st = "✅达标" if r["best"] >= r["target"] else ("🟡接近" if r["target"] - 5 <= r["best"] < r["target"] else "❌未达标")
        q = r["question"].replace("|", "/").strip()
        if len(q) > 42: q = q[:42] + "…"
        lines.append(f"| {r['id']} | {day} | {r['target']} | {r['best']} | {rs[-1][1]} | {len(rs)} | {st} | {q} |")
    for day, runs, nod in groups:
        for r in runs:
            row(r, day)
        for r in nod:
            lines.append(f"| {r['id']} | {day} | 90 | - | - | - | ⚪无分数数据 | {r['question']} |")
    parts = []
    for day, runs, nod in groups:
        p = sum(1 for r in runs if r["best"] >= r["target"])
        parts.append(f"{day} 共 {len(runs)} 次（另有 {len(nod)} 次无分数数据），达标 {p}")
    lines.insert(2, f"- 汇总：{'；'.join(parts)}。")
    lines.insert(2, f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    out_md = os.path.join(BASE, f"运行总览_对照表_{stamp}.md")
    with io.open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"图已生成：{out_png}")
    print(f"表已生成：{out_md}")
    for day, runs, nod in groups:
        p = sum(1 for r in runs if r["best"] >= r["target"])
        print(f"{day} 运行数={len(runs)} 达标={p}")

if __name__ == "__main__":
    main()