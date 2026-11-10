# -*- coding: utf-8 -*-
"""L5 验收：离线断言脚本（不调 API）。验证批次 C/D 的纯代码机制：
1) merge_points 归档/复活
2) _paper_relevant_query（L6 term 级匹配）
3) _tree_rebuild_needed（L7 双条件）
4) _hash12/_body_for_hash（N6）
5) route_review 收敛按 tree_version 隔离（L7）
6) L4 分歧触发条件、L6 cdr 语义（模拟 review 内逻辑）
"""
import io, os, sys, json, difflib, re

SRC = r"C:\Users\22011\Desktop\26暑假\ai_scientist\src"
sys.path.insert(0, SRC)

import langgraph_agent as L

results = []
def check(name, ok, detail=""):
    results.append((name, bool(ok)))
    print(("PASS  " if ok else "FAIL  ") + name + ((" | " + detail) if detail else ""))

# ---------- 1) merge_points 归档 ----------
pts = [
    {"id": 1, "name": "样本量计算", "history": [
        {"round": 1, "score": 90, "status": "active"},
        {"round": 2, "score": 90, "status": "active"},
    ]},
    {"id": 2, "name": "统计判据", "history": [
        {"round": 1, "score": 85, "status": "active"},
        {"round": 2, "score": 90, "status": "active"},
    ]},
]
# 第 3 轮：评审没提这两个点（reasons 空），bottleneck 与它们无关 -> 连续 2 轮 >=88 且未被引用 -> 归档
out = L.merge_points(pts, [{"id": 1, "name": "样本量计算", "score": 90, "status": "active"},
                            {"id": 2, "name": "统计判据", "score": 90, "status": "active"}],
                      round_no=3, reasons=None, reasons_text="评审意见与其它维度相关", prev_reasons_text="", bottleneck="feasibility")
b1 = [p for p in out if p["id"] == 1][0]
b2 = [p for p in out if p["id"] == 2][0]
check("L3 归档: 连续2轮>=88 未引用 -> archived", b1["history"][-1]["status"] == "archived", str(b1["history"][-1]))
check("L3 归档: 非焦点未提及不误归档", b2["history"][-1]["status"] == "archived", str(b2["history"][-1]))

# 被引用的不归档
pts3 = [
    {"id": 1, "name": "样本量计算", "history": [
        {"round": 1, "score": 90, "status": "active"},
        {"round": 2, "score": 90, "status": "active"},
    ]},
]
out3 = L.merge_points(pts3, [{"id": 1, "name": "样本量计算", "score": 90, "status": "active"}],
                      round_no=3, reasons=None, reasons_text="样本量计算仍需交代组内重复", prev_reasons_text="", bottleneck="")
check("L3 归档: 本轮被引用 -> 不归档", out3[0]["history"][-1]["status"] == "active", str(out3[0]["history"][-1]))

# 分数不足 88 不归档
pts4 = [{"id": 1, "name": "x", "history": [{"round": 1, "score": 85, "status": "active"}]}]
out4 = L.merge_points(pts4, [{"id": 1, "name": "x", "score": 85, "status": "active"}], round_no=2, reasons_text="", prev_reasons_text="", bottleneck="")
check("L3 归档: 分数<88 不归档", out4[0]["history"][-1]["status"] == "active")

# ---------- 2) merge_points 复活 ----------
pts5 = [
    {"id": 1, "name": "样本量重复说明", "history": [{"round": 2, "score": 90, "status": "archived"}]},
]
reasons5 = [{"related_point_id": 1, "issue": "样本量重复说明：新改法后样本量未交代", "dimension": "feasibility"}]
out5 = L.merge_points(pts5, [{"id": 1, "name": "样本量重复说明", "score": 90, "status": "archived"}],
                      round_no=3, reasons=reasons5, reasons_text="", prev_reasons_text="", bottleneck="")
check("L3 复活: related_point_id+负面语义 -> active", out5[0]["history"][-1]["status"] == "active", str(out5[0]["history"][-1]))

# 名称相似 >0.8 复活（rid=None）
pts6 = [{"id": 1, "name": "样本量与重复次数说明", "history": [{"round": 2, "score": 90, "status": "archived"}]}]
reasons6 = [{"issue": "样本量与重复次数说明需要补全"}]
out6 = L.merge_points(pts6, [{"id": 1, "name": "样本量与重复次数说明", "score": 90, "status": "archived"}],
                      round_no=3, reasons=reasons6, reasons_text="", prev_reasons_text="", bottleneck="")
check("L3 复活: 名称相似>0.8 -> active", out6[0]["history"][-1]["status"] == "active", str(out6[0]["history"][-1]))

# 负面语义缺失不复活（N2 防抖动）
pts7 = [{"id": 1, "name": "样本量说明", "history": [{"round": 2, "score": 90, "status": "archived"}]}]
reasons7 = [{"related_point_id": 1, "issue": "样本量说明已满足"}]
out7 = L.merge_points(pts7, [{"id": 1, "name": "样本量说明", "score": 90, "status": "archived"}],
                      round_no=3, reasons=reasons7, reasons_text="", prev_reasons_text="", bottleneck="")
check("L3 复活: 无负面语义不复活", out7[0]["history"][-1]["status"] == "archived", str(out7[0]["history"][-1]))

# ---------- 3) L6 _paper_relevant_query ----------
check("L6 英文双term命中", L._paper_relevant_query("perovskite solar cell stability", "Stability of perovskite solar cells under damp heat") is True)
check("L6 英文单term命中", L._paper_relevant_query("machine learning battery", "Machine learning for battery health") is True)
check("L6 英文零命中", L._paper_relevant_query("quantum entanglement", "Perovskite solar cell efficiency record") is False)
check("L6 中文子串命中", L._paper_relevant_query("钙钛矿 太阳能电池 稳定性", "钙钛矿太阳能电池的长期稳定性研究") is True)
check("L6 中文零命中", L._paper_relevant_query("锂电池 寿命预测", "钙钛矿薄膜的制备工艺优化") is False)
check("L6 空query放行", L._paper_relevant_query("", "Anything at all") is True)
check("L6 term不足放行", L._paper_relevant_query("ab", "some title about ab") is True)

# ---------- 4) L7 _tree_rebuild_needed ----------
check("L7 双条件(>=3 且 >=50%)", L._tree_rebuild_needed(3, 6) is True)
check("L7 3篇池+2新增不触发", L._tree_rebuild_needed(2, 5) is False)
check("L7 4/10 新增不触发(<50%)", L._tree_rebuild_needed(4, 10) is False)
check("L7 空池不触发", L._tree_rebuild_needed(3, 0) is False)

# ---------- 5) N6 hash ----------
h1 = L._hash12(L._body_for_hash("假设正文【修改说明】改了X"))
h2 = L._hash12("假设正文")
check("N6 body_hash 剥离修改说明", h1 == h2, f"{h1} vs {h2}")
check("N6 body_hash 12位", len(h1) == 12)

# ---------- 6) route_review 收敛 tree_version 隔离 ----------
def mk_state(hist, tv):
    return {
        "rounds": len(hist), "score_history": hist, "tree_version": tv,
        "data_score": 90, "consecutive_data_rounds": 0, "total_data_rounds": 0,
        "p10_forced": False, "platform_active": False, "search_requested": False,
        "search_exhausted": False, "soft_search_rounds": 0,
        "total_soft_searches": 0, "platform_suggestion": "", "hypothesis_score": hist[-1]["hypothesis_score"] if hist else 0,
    }
# 同版本停滞 -> END
st1 = mk_state([
    {"round": 1, "hypothesis_score": 70, "data_score": 90, "tree_version": 0},
    {"round": 2, "hypothesis_score": 80, "data_score": 90, "tree_version": 0},
    {"round": 3, "hypothesis_score": 80, "data_score": 90, "tree_version": 0},
    {"round": 4, "hypothesis_score": 80, "data_score": 90, "tree_version": 0},
], 0)
check("L7 同版本停滞 -> 收敛END", L.route_review(st1) == L.END)
# 跨版本跃升（重拆后）不误停
st2 = mk_state([
    {"round": 1, "hypothesis_score": 70, "data_score": 90, "tree_version": 0},
    {"round": 2, "hypothesis_score": 78, "data_score": 90, "tree_version": 0},
    {"round": 3, "hypothesis_score": 82, "data_score": 90, "tree_version": 0},
    {"round": 4, "hypothesis_score": 80, "data_score": 90, "tree_version": 1},
    {"round": 5, "hypothesis_score": 88, "data_score": 90, "tree_version": 1},
    {"round": 6, "hypothesis_score": 88, "data_score": 90, "tree_version": 1},
], 1)
check("L7 重拆后新版本跃升 -> 不误收敛", L.route_review(st2) != L.END, str(L.route_review(st2)))
# 跨版本窗口不足不判（traj_c）
st3 = mk_state([
    {"round": 1, "hypothesis_score": 70, "data_score": 90, "tree_version": 0},
    {"round": 2, "hypothesis_score": 78, "data_score": 90, "tree_version": 0},
    {"round": 3, "hypothesis_score": 82, "data_score": 90, "tree_version": 0},
    {"round": 4, "hypothesis_score": 82, "data_score": 90, "tree_version": 0},
    {"round": 5, "hypothesis_score": 88, "data_score": 90, "tree_version": 1},
], 1)
check("L7 跨版本窗口不足 -> 不误判", L.route_review(st3) != L.END, str(L.route_review(st3)))

# ---------- 7) L4 触发条件 + L6 cdr 语义（模拟 review 内逻辑） ----------
# cdr：last_new_relevant>0 -> 归零
def cdr_sim(last_new_relevant, data_mode, prev_cdr):
    if last_new_relevant > 0:
        return 0
    elif data_mode:
        return prev_cdr + 1
    return 0
check("L6 cdr: 相关新增>0 归零", cdr_sim(2, True, 1) == 0)
check("L6 cdr: 相关新增=0 且数据模式 累计", cdr_sim(0, True, 1) == 2)
check("L6 cdr: 相关新增=0 非数据模式 归零", cdr_sim(0, False, 1) == 0)

# L4 触发：|delta|>10
def trig_sim(score_corrected, data_corrected, degraded, delta, sim, prev):
    jf = bool(degraded and ("score_trace" in degraded or "json_fallback" in degraded
                            or "json_chat 失败" in degraded or "兜底链" in degraded))
    return (score_corrected or data_corrected or jf or abs(delta) > 10 or (sim > 0.95 and abs(delta) >= 5)) and prev < 2
check("L4 触发: 大跳变 |delta|>10", trig_sim(False, False, "", 11, 0.5, 0) is True)
check("L4 触发: json_fallback", trig_sim(False, False, "json_chat 失败，进入兜底链", 3, 0.5, 0) is True)
check("L4 触发: 高相似+delta>=5", trig_sim(False, False, "", 5, 0.96, 0) is True)
check("L4 触发: 高相似 delta=2 不触发", trig_sim(False, False, "", 2, 0.96, 0) is False)
check("L4 触发: 探测次数达上限不触发", trig_sim(True, False, "", 3, 0.5, 2) is False)

# ---------- 8) L5 JSONL 行结构（模拟组装） ----------
row = {
    "ts": "x", "run_no": 1, "round": 2, "mode": "hypothesis",
    "hypothesis_score": 88, "data_score": 70,
    "input": {"body_hash": L._hash12("body"), "literature_hash": L._hash12("t1\nt2"), "gap_hash": L._hash12("gap")},
    "output": {"reasons": [], "points": [], "search_request": None, "score_trace": None},
    "perf": {"duration_s": 1.0, "tokens": 100, "attempts": 1},
    "divergence": None, "probe_failed": False, "tree_version": 0,
}
req = ["ts", "run_no", "round", "mode", "hypothesis_score", "data_score", "input", "output", "perf", "divergence", "probe_failed", "tree_version"]
check("L5 行含全部必填字段", all(k in row for k in req))
check("L5 行含 body_hash/literature_hash/gap_hash", all(k in row["input"] for k in ("body_hash", "literature_hash", "gap_hash")))

# _append_review_jsonl 实际落盘
import tempfile
with tempfile.TemporaryDirectory() as td:
    st = {"run_folder": td}
    L._append_review_jsonl(st, row)
    path = os.path.join(td, "03_评审JSONL.jsonl")
    check("L5 落盘文件存在", os.path.isfile(path))
    if os.path.isfile(path):
        with io.open(path, "r", encoding="utf-8") as f:
            line = f.readline().strip()
        parsed = json.loads(line)
        check("L5 落盘行可解析且含 tree_version", parsed.get("tree_version") == 0 and parsed.get("hypothesis_score") == 88)

ok_count = sum(1 for _, ok in results if ok)
print("\n===== 汇总: %d/%d PASS =====" % (ok_count, len(results)))
sys.exit(0 if ok_count == len(results) else 1)