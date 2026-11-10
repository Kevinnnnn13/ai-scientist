"""search_crossref.py：CrossRef 论文溯源 —— Agent 的"眼睛"③：DOI -> 参考文献

CrossRef 是 DOI 的官方注册机构（免费开放 API，无 key）：
1. 输入 DOI，返回这篇论文的完整元数据 + 参考文献列表
2. 用途：从"种子论文"顺藤摸瓜，扩展文献池、看清领域脉络

用法：
    python src/search_crossref.py
    python src/search_crossref.py "10.1038/s41560-019-0356-8"
"""
import sys

import requests

API = "https://api.crossref.org/works/"


def fetch_work(doi):
    """按 DOI 获取论文元数据（标题/期刊/年份/参考文献列表）。

    结构完全复用 search_papers.py 的模式：
    请求 -> raise_for_status() 大声报错 -> 取 JSON -> 返回
    """
    url = API + doi
    # mailto：和 OpenAlex 一样的礼貌池机制（免费 API 的通用约定）
    resp = requests.get(url, params={"mailto": "buaa_student@example.com"}, timeout=30)
    resp.raise_for_status()          # 失败就抛异常，别静默
    return resp.json()["message"]    # CrossRef 的正文都在 "message" 里


def paper_summary(work):
    """从 CrossRef 的原始结构里抽出我们关心的字段。

    CrossRef 返回的字段很绕（title 是列表、日期嵌套在 date-parts 里），
    所以抽一个"翻译"函数，把官方结构转成好用的字典。
    """
    title = (work.get("title") or [""])[0]                  # title 是数组，取第一个
    journal = (work.get("container-title") or [""])[0]      # 期刊名也是数组
    year = None
    for key in ("published-print", "published-online", "issued"):
        date_parts = work.get(key, {}).get("date-parts")
        if date_parts and date_parts[0]:
            year = date_parts[0][0]                         # [[2026, 8, 3]] -> 2026
            break
    return {
        "标题": title,
        "期刊": journal,
        "年份": year,
        "DOI": work.get("DOI"),
        "参考文献数": len(work.get("reference", [])),
    }


def show(work):
    """打印论文信息 + 前 5 条参考文献"""
    info = paper_summary(work)
    print(f"标题：{info['标题']}")
    print(f"期刊：{info['期刊']} | 年份：{info['年份']} | DOI：{info['DOI']}")
    print(f"参考文献数：{info['参考文献数']} 条")
    print("\n前 5 条参考文献：")
    for i, ref in enumerate(work.get("reference", [])[:5], 1):
        title = ref.get("article-title") or ref.get("unstructured") or "(无标题)"
        print(f"  [{i}] {title}")


if __name__ == "__main__":
    # 默认用 Severson 那篇电池寿命的 Nature Energy 论文（昨天 OpenAlex 搜到过）
    doi = sys.argv[1] if len(sys.argv) > 1 else "10.1038/s41560-019-0356-8"
    print(f"正在查询 DOI：{doi}")
    show(fetch_work(doi))
