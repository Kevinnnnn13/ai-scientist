import sys
sys.path.insert(0, "src")
from langgraph_agent import graph

print(graph.get_graph().draw_mermaid())