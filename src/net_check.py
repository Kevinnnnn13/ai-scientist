# -*- coding: utf-8 -*-
"""net_check.py：关掉梯子（中本）后运行，验证外网检索 + DeepSeek 全链路。
用法：python src\net_check.py  （或运行 run_net_check.ps1）"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))

ok_all = True

print("== 1) OpenAlex（论文检索）==")
try:
    import requests
    r = requests.get("https://api.openalex.org/works", params={"search": "perovskite", "per-page": 1}, timeout=15)
    if r.status_code == 200:
        print("  OK: HTTP", r.status_code)
    else:
        ok_all = False
        print("  FAIL: HTTP", r.status_code, "(非 200，可能限流)")
except Exception as e:
    ok_all = False
    print("  FAIL:", type(e).__name__, e)

print("== 2) Tavily（网页检索）==")
try:
    from tavily import TavilyClient
    c = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    r = c.search(query="perovskite solar cell", max_results=1)
    print("  OK: results =", len(r.get("results", [])))
except Exception as e:
    ok_all = False
    print("  FAIL:", type(e).__name__, e)

print("== 3) DeepSeek（本地 8787 代理）==")
try:
    import llm_client
    c, model = llm_client.get_client()
    resp = c.chat.completions.create(model=model,
                                     messages=[{"role": "user", "content": "只回复两个字：正常"}], max_tokens=10)
    print("  OK:", resp.choices[0].message.content[:30])
except Exception as e:
    ok_all = False
    print("  FAIL:", type(e).__name__, e)

print()
if ok_all:
    print("===== 全部通过：外网检索 + DeepSeek 都通，可以跑全量 =====")
else:
    print("===== 有失败项：看上面哪个 FAIL ===")
