"""peek_api.py：观察 Tavily 返回结构的完整样子（探索 API 的解剖刀）"""
from search_web import search_web

results = search_web("AI 新闻", max_results=2, topic="news")
print("类型：", type(results), "| 长度：", len(results))
first = results[0]
print("一条结果的类型：", type(first))
print("一条结果的所有键：", list(first.keys()))
print("完整内容：", first)