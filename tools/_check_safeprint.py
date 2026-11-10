import io
ls = io.open(r"src\langgraph_agent.py", encoding="utf-8").read().splitlines()
print("safe_print call count:", sum(1 for l in ls if "_safe_print(" in l and "def _safe_print" not in l))
print("raw LLM prints remaining:", sum(1 for l in ls if 'print(f"\\n[LLM]' in l or 'print(f"\\n[假设生成]' in l or 'print(f"\\n[缺口分析]' in l or 'print(f"  {k}: {v}")' in l or 'print("\\n[白板]' in l))
for i, l in enumerate(ls):
    if "_safe_print(" in l and "def _safe_print" not in l:
        print(i + 1, l.strip()[:80])
