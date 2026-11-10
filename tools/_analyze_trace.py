# -*- coding: utf-8 -*-
"""临时：打印指定运行的 score_history 细节 + 回跳轮评审原文。"""
import json
import io
import sys

state_path = sys.argv[1]
s = json.load(io.open(state_path, encoding="utf-8"))
sh = s.get("score_history") or []
for i, h in enumerate(sh):
    print(f"R{i+1}: hyp={h.get('hypothesis_score')} data={h.get('data_score')} "
          f"data_corrected={h.get('data_corrected')} forced={h.get('data_forced_kind')} "
          f"gated={h.get('self_gated')} tv={h.get('tree_version')} "
          f"ev_basis={h.get('evidence_basis')}")
print("consecutive_data_rounds:", s.get("consecutive_data_rounds"),
      "total_data_rounds:", s.get("total_data_rounds"),
      "search_exhausted:", s.get("search_exhausted"),
      "gap_confirmed:", s.get("gap_confirmed"))
