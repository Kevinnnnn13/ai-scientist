"""search_web.py：Tavily 联网搜索 —— Agent 的"眼睛"①：搜索网页

用法：
    python src/search_web.py
    python src/search_web.py "你的搜索词"
"""
import os
import sys

from dotenv import load_dotenv
from tavily import TavilyClient

load_dotenv()


def search_web(query, max_results=5, topic=None, days=None):
    """联网搜索，返回 [{title, url, content, score, published_date, ...}, ...]

    topic: None=综合网页, "news"=新闻, "finance"=财经
    days: 只看最近 N 天（Tavily 仅对 news/finance 生效），如 days=2
    """
    kwargs = {
        "query": query,
        "max_results": max_results,
        "include_answer": False,
        "timeout": 30,              # 超时保护：30 秒没响应就抛 TimeoutError，绝不无限挂起
    }
    if topic:
        kwargs["topic"] = topic
    if days:
        kwargs["days"] = days
    # 网络容错（2026-08-10）：超时/429/断线自动重试 2 次，退避 3s/10s；全败返回空列表
    import time as _t
    last_err = None
    for attempt in range(3):
        try:
            client = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
            resp = client.search(**kwargs)
            return resp.get("results", [])
        except Exception as _e:
            last_err = _e
            if attempt < 2:
                _t.sleep(3 if attempt == 0 else 10)
    print(f"[search_web] 3 次尝试均失败：{last_err}")
    # 全败抛异常（2026-08-29 稳定性优化）：让 call_tool 返回失败 Observation，
    # 明确告知 Agent「检索暂不可用」，避免把「服务不可用」误判成「没搜到」而反复重试烧 token。
    raise ConnectionError(
        "网页检索服务暂不可用（Tavily 连接失败），请基于已有知识或文献直接回答，不要重复搜索。"
    )


def show(results):
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.get('title')}")
        print(f"    链接: {r.get('url')}")
        print(f"    摘要: {(r.get('content') or '')[:120]}")
        print()


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "今天 AI 领域最重要的新闻"
    print(f"正在联网搜索：{q}")
    show(search_web(q, max_results=5, topic="news"))
