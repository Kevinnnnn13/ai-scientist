# -*- coding: utf-8 -*-
"""临时：读批跑 _progress.json + 各 state.json，输出逐题维度/轨迹/瓶颈分析。"""
import json
import io
import os
import glob
import sys

base = sys.argv[1]
p = json.load(io.open(os.path.join(base, "_progress.json"), encoding="utf-8"))
print(f"== 已批跑 {p['done']}/{p['total']} 题 ==")

rows = []
for d in sorted(glob.glob(os.path.join(base, "q*"))):
    m = os.path.basename(d).split("_")[0]
    no = int(m[1:])
    sjs = glob.glob(os.path.join(d, "**", "state.json"), recursive=True)
    if not sjs:
        continue
    s = json.load(io.open(sjs[0], encoding="utf-8"))
    dims = s.get("dimensions") or {}
    traj = [(h.get("hypothesis_score"), h.get("data_score")) for h in (s.get("score_history") or [])]
    rows.append({
        "no": no, "best": s.get("best_score"), "bd": s.get("best_data_score"),
        "dims": dims, "bottle": s.get("bottleneck"), "traj": traj,
        "rounds": s.get("rounds"), "cost": s.get("api_cost_cny"),
        "q": str(s.get("question") or "")[:46],
    })

rows.sort(key=lambda x: x["no"])
for x in rows:
    d = x["dims"]
    print(f"Q{x['no']:>2} best={x['best']} data={x['bd']:>3} r={x['rounds']} "
          f"[T{d.get('testability')} E{d.get('evidence')} F{d.get('feasibility')} N{d.get('novelty')}] "
          f"瓶颈={x['bottle']} 轨迹={x['traj']} | {x['q']}")

if rows:
    bs = [r["best"] for r in rows if r["best"] is not None]
    print(f"\n均值 best={sum(bs)/len(bs):.1f}  范围 {min(bs)}-{max(bs)}  轮次均值 {sum(r['rounds'] or 0 for r in rows)/len(rows):.1f}")
    import collections
    bn = collections.Counter(r["bottle"] for r in rows if r["bottle"])
    print("瓶颈分布:", dict(bn))
    ev = [r["dims"].get("evidence") for r in rows if r["dims"].get("evidence") is not None]
    te = [r["dims"].get("testability") for r in rows if r["dims"].get("testability") is not None]
    fe = [r["dims"].get("feasibility") for r in rows if r["dims"].get("feasibility") is not None]
    no = [r["dims"].get("novelty") for r in rows if r["dims"].get("novelty") is not None]
    print(f"四维均值: testability={sum(te)/len(te):.0f} evidence={sum(ev)/len(ev):.0f} feasibility={sum(fe)/len(fe):.0f} novelty={sum(no)/len(no):.0f}")
