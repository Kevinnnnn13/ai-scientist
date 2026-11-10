"""search_papers.py：OpenAlex 学术检索 —— Agent 的"眼睛"②：搜论文（免费，无需 key）

用法：
    python src/search_papers.py
    python src/search_papers.py "battery remaining useful life"
"""
import sys

import requests

API = "https://api.openalex.org/works"
S2_API = "https://api.semanticscholar.org/graph/v1/paper/search"
CROSSREF_API = "https://api.crossref.org/works"


def search_papers(query, per_page=5, mailto=None):
    """按关键词搜学术论文，返回原始结果列表

    关键经验（今天踩过的坑）：
    1. 用 filter=title_and_abstract.search 只在「标题+摘要」里搜，
       不要用 search= 全文搜（匹配太宽泛）；
    2. 不要用 sort=cited_by_count:desc 排序——被引排序会把
       「最热门但不相关」的论文顶到最前面，要用默认的相关度排序。

    mailto: 传邮箱 → 进入 OpenAlex「礼貌池」（优先模式），
            请求优先级更高，批量检索更不容易被限流；
            不传 → 普通模式。
    """
    params = {
        "filter": f"title_and_abstract.search:{query}",
        "per-page": per_page,
    }
    if not mailto:                   # 环境变量 OPENALEX_MAILTO 可提供邮箱进入礼貌池（降限流）
        import os as _os
        mailto = _os.getenv("OPENALEX_MAILTO") or None
    if mailto:                       # 提供邮箱 → 优先模式
        params["mailto"] = mailto
    # 网络容错（2026-08-10）：超时/429/断线自动重试；429 用更长退避（限流恢复后重试）
    import time as _t
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.get(API, params=params, timeout=30)
            if resp.status_code == 429:
                _ra = resp.headers.get("Retry-After")
                try:
                    wait_raw = float(_ra) if _ra else 0.0
                except (TypeError, ValueError):
                    wait_raw = 0.0
                last_err = f"HTTP 429 限流（Retry-After={_ra}）"
                if wait_raw > 120:
                    break
                wait = min(wait_raw, 30.0)
                if attempt < 3:
                    _t.sleep(wait if wait > 0 else (5, 15, 30)[attempt])
                continue
            resp.raise_for_status()
            return resp.json().get("results", [])
        except Exception as _e:
            last_err = _e
            if attempt < 3:
                _t.sleep((3, 10, 20)[attempt])
    print(f"[search_papers] OpenAlex 检索失败（{last_err}），切换备用论文源…")
    return fallback_search(query, per_page)


def ask_mailto():
    """交互询问：是否提供邮箱进入 OpenAlex 优先模式"""
    print("OpenAlex 两种模式：")
    print("  优先模式：提供邮箱，进入礼貌池，请求更快、批量检索不容易被限流")
    print("  普通模式：不提供邮箱，直接用")
    answer = input("是否提供邮箱进入优先模式？(y/n，直接回车=普通模式) ").strip().lower()
    if answer not in ("y", "yes", "是"):
        print("→ 普通模式")
        return None
    email = input("请输入你的邮箱（如 name@buaa.edu.cn）：").strip()
    if not email or "@" not in email:
        print("→ 邮箱无效，回退普通模式")
        return None
    print(f"→ 优先模式（礼貌池），邮箱：{email}")
    return email


def paper_to_dict(p):
    """把 OpenAlex 的一条结果整理成好用的字典"""
    authors = [a["author"]["display_name"] for a in p.get("authorships", [])][:3]
    source = (p.get("primary_location") or {}).get("source") or {}
    return {
        "标题": p.get("title"),
        "年份": p.get("publication_year"),
        "作者": "、".join(authors),
        "期刊": source.get("display_name"),
        "被引次数": p.get("cited_by_count"),
        "DOI": p.get("doi"),
    }


def show(papers):
    for i, p in enumerate(papers, 1):
        info = paper_to_dict(p)
        print(f"[{i}] {info['标题']}")
        print(f"    {info['年份']} | 期刊: {info['期刊']} | 被引: {info['被引次数']}")
        print(f"    作者: {info['作者']}")
        print(f"    DOI: {info['DOI']}")
        print()




def fallback_search(query, per_page=5):
    """OpenAlex 失败时的备用论文源：Semantic Scholar → Crossref（均免费、无需 key）。

    返回结构与 OpenAlex 兼容（title/publication_year/authorships/
    primary_location/cited_by_count/doi），调用方的 paper_to_dict 无需改动。
    """
    errors = []
    for name, func in (("Semantic Scholar", _s2_search), ("Crossref", _crossref_search)):
        try:
            papers = func(query, per_page)
            if papers:
                print(f"[search_papers] 备用源 {name} 命中 {len(papers)} 条")
                return papers
            print(f"[search_papers] 备用源 {name} 无结果")
        except Exception as exc:
            errors.append(f"{name}({type(exc).__name__})")
            print(f"[search_papers] 备用源 {name} 失败：{type(exc).__name__}: {exc}")
    if errors:
        # 全部源连接失败（2026-08-29 稳定性优化）：抛异常让 call_tool 返回失败 Observation，
        # 明确告知 Agent「检索暂不可用」，避免把「服务不可用」误判成「没搜到」而反复重试烧 token。
        raise ConnectionError(
            "学术论文检索服务暂不可用（OpenAlex 失败，备用源 " + "、".join(errors) + " 均连接失败）。"
            "请基于已有知识或文献直接回答，不要重复搜索。"
        )
    return []


def search_recent_papers(query, per_page=5, years=3, mailto=None):
    """跨源搜索「最近 years 年」的文献（前沿风向模块用，2026-08-29 新增）。

    源顺序：OpenAlex(日期过滤+按发表时间降序) → Semantic Scholar(年份过滤) → Crossref(日期过滤)。
    任一源成功即返回；全部失败返回 []（静默——旁路模块，不让主流程崩）。
    返回结构与 search_papers 一致（OpenAlex 原始结构），调用方用 paper_to_dict 转换。
    """
    from datetime import date
    import os as _os
    start_date = f"{date.today().year - int(years)}-01-01"
    start_year = date.today().year - int(years)
    errors = []
    # 1) OpenAlex：标题+摘要搜索 + 日期过滤 + 按发表时间降序
    params = {
        "filter": f"title_and_abstract.search:{query},from_publication_date:{start_date}",
        "per-page": per_page,
        "sort": "publication_date:desc",
    }
    mailto = mailto or _os.getenv("OPENALEX_MAILTO") or None
    if mailto:
        params["mailto"] = mailto
    # 网络容错：429/超时/断线重试（对齐 search_papers 主链路的退避策略）
    import time as _t
    last_err = None
    for attempt in range(4):
        try:
            resp = requests.get(API, params=params, timeout=30)
            if resp.status_code == 429:
                _ra = resp.headers.get("Retry-After")
                try:
                    wait_raw = float(_ra) if _ra else 0.0
                except (TypeError, ValueError):
                    wait_raw = 0.0
                last_err = f"HTTP 429（Retry-After={_ra}）"
                if wait_raw > 120:
                    break
                if attempt < 3:
                    _t.sleep(min(wait_raw, 30.0) if wait_raw > 0 else (5, 15, 30)[attempt])
                continue
            resp.raise_for_status()
            res = resp.json().get("results", [])
            if res:
                print(f"[search_recent] OpenAlex 命中 {len(res)} 条（{start_date} 起）")
                return res
            errors.append("OpenAlex(空)")
            break
        except Exception as exc:
            last_err = exc
            if attempt < 3:
                _t.sleep((3, 10, 20)[attempt])
    if last_err:
        errors.append(f"OpenAlex({type(last_err).__name__})")
    # 2) Semantic Scholar（年份过滤）
    try:
        res = _s2_search(query, per_page, year=f"{start_year}-{date.today().year}")
        if res:
            print(f"[search_recent] Semantic Scholar 命中 {len(res)} 条（{start_year} 起）")
            return res
        errors.append("S2(空)")
    except Exception as exc:
        errors.append(f"S2({type(exc).__name__})")
    # 3) Crossref（日期过滤）
    try:
        res = _crossref_search(query, per_page, from_date=start_date)
        if res:
            print(f"[search_recent] Crossref 命中 {len(res)} 条（{start_date} 起）")
            return res
        errors.append("Crossref(空)")
    except Exception as exc:
        errors.append(f"Crossref({type(exc).__name__})")
    if errors:
        print(f"[search_recent] 全部源无近年文献：{'；'.join(errors)}")
    return []


def _s2_search(query, per_page=5, year=None):
    """Semantic Scholar 关键词搜索 -> OpenAlex 兼容结构"""
    params = {
        "query": query,
        "limit": per_page,
        "fields": "title,year,authors,venue,externalIds,citationCount",
    }
    if year:
        params["year"] = year          # 形如 "2023-2026"
    resp = requests.get(S2_API, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json().get("data") or []
    out = []
    for item in data:
        authorships = [
            {"author": {"display_name": a.get("name", "")}}
            for a in (item.get("authors") or [])[:3]
        ]
        doi = (item.get("externalIds") or {}).get("DOI")
        out.append({
            "title": item.get("title"),
            "publication_year": item.get("year"),
            "authorships": authorships,
            "primary_location": {"source": {"display_name": item.get("venue") or None}},
            "cited_by_count": item.get("citationCount"),
            "doi": doi,
        })
    return out


def _crossref_search(query, per_page=5, from_date=None):
    """Crossref 关键词搜索 -> OpenAlex 兼容结构"""
    params = {
        "query": query,
        "rows": per_page,
        "select": "title,container-title,issued,DOI,author,is-referenced-by-count",
        "mailto": "buaa_student@example.com",
    }
    if from_date:
        params["filter"] = f"from-pub-date:{from_date}"     # 形如 2023-01-01
    resp = requests.get(CROSSREF_API, params=params, timeout=30)
    resp.raise_for_status()
    items = resp.json().get("message", {}).get("items") or []
    out = []
    for item in items:
        title = (item.get("title") or [""])[0]
        doi = item.get("DOI")
        if not title.strip() or not doi:
            continue
        if doi.startswith("10.3030/"):      # EU 项目 grant，非论文
            continue
        authorships = [
            {"author": {"display_name": f"{a.get('given', '')} {a.get('family', '')}".strip()}}
            for a in (item.get("author") or [])[:3]
        ]
        year = None
        for key in ("published-print", "published-online", "issued"):
            dp = item.get(key, {}).get("date-parts")
            if dp and dp[0]:
                year = dp[0][0]
                break
        out.append({
            "title": title,
            "publication_year": year,
            "authorships": authorships,
            "primary_location": {"source": {"display_name": (item.get("container-title") or [""])[0]}},
            "cited_by_count": item.get("is-referenced-by-count"),
            "doi": doi,
        })
    return out


if __name__ == "__main__":
    q = sys.argv[1] if len(sys.argv) > 1 else "lithium-ion battery remaining useful life"
    print(f"正在检索论文：{q}")
    mailto = ask_mailto()            # 先交互询问邮箱，再搜索
    show(search_papers(q, mailto=mailto))
