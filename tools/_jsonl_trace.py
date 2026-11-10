# -*- coding: utf-8 -*-
"""临时：打印评审 JSONL 每轮的关键字段。用法：python tools/_jsonl_trace.py <jsonl路径>"""
import json
import io
import sys

path = sys.argv[1]
rows = [json.loads(l) for l in io.open(path, encoding="utf-8") if l.strip()]
for i, r in enumerate(rows, 1):
    print("R%d: gap_in=%s mode=%s data=%s hyp=%s data_mode=%s cdr=%s total=%s forced=%s p10=%s latched=%s" % (
        i, r.get("gap_confirmed"), r.get("mode"), r.get("data_score"),
        r.get("hypothesis_score"), r.get("data_mode"),
        r.get("consecutive_data_rounds"), r.get("total_data_rounds"),
        r.get("data_forced_kind"), r.get("p10_forced"), r.get("gap_confirmed_latched")))
