import io
ls = io.open(r"src\langgraph_agent.py", encoding="utf-8").read().splitlines()
pats = ['print(f"\\n[LLM]', 'print(f"\\n[假设生成]', 'print(f"\\n[缺口分析]', 'print(f"  {k}: {v}")', 'print("\\n[白板]']
for i, l in enumerate(ls):
    if any(pp in l for pp in pats):
        print(i + 1, repr(l))
