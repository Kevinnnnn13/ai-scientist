# -*- coding: utf-8 -*-
"""用户画像模块（2026-08-28 新增）。

原理：用户累计提问 >= 5 次后，把历史运行（问题 + 追问回答 + 知识树检索词 + 文献标题）
压缩成摘要，交给 LLM 做细粒度领域推断：学科(discipline) → 子领域(subfield) →
主题(topic) → 方法(method)，输出权重、置信度与推断依据。

架构（可插拔）：
  PROFILE_BACKEND=llm（默认）→ LLM 直接推断
  PROFILE_BACKEND=zep    → 尝试 Zep Cloud 动态知识图谱后端；未配置/失败自动落回 LLM
  episodes：每次运行把「问题/追问/检索词/文献」按 Zep Episode 兼容格式落盘到
  users/<用户名>/episodes.jsonl，后续可批量灌入 Zep/Graphiti。

fail-open：样本不足、LLM 异常、Zep 不可用，一律返回 ready=False，不阻塞主流程。
"""
import io
import json
import os
import sys
import time

SRC = os.path.dirname(os.path.abspath(__file__))
USERS_ROOT = os.path.join(SRC, "users")
LOGS_DIR = os.path.join(SRC, "logs")
MIN_SAMPLES = 5          # 累计有效运行数达到该值才生成画像
EPISODE_LIMIT = 20       # 参与画像的历史条数上限
DIGEST_CHARS = 4000      # 喂给 LLM 的摘要长度上限


def _import_user_store():
    sys.path.insert(0, SRC)
    import user_store
    return user_store


def _done_records(username):
    """该用户状态为 done 且有结果目录的历史记录（新的在前）。"""
    try:
        us = _import_user_store()
        history = us.list_history(username, limit=50)
    except Exception:
        return []
    return [r for r in history if r.get("status") == "done" and r.get("folder")
            and os.path.isdir(str(r.get("folder") or ""))]


def _read_clarify(run_id):
    """从 src\\logs\\api_<run_id>.clarify.json 读追问 Q&A。"""
    if not run_id:
        return []
    try:
        fp = os.path.join(LOGS_DIR, "api_%s.clarify.json" % run_id)
        with io.open(fp, encoding="utf-8") as f:
            data = json.load(f)
        return [{"q": str(x.get("question") or "")[:120], "a": str(x.get("answer") or "")[:200]}
                for x in data if isinstance(x, dict) and str(x.get("answer") or "").strip()]
    except Exception:
        return []


def collect_episodes(username, limit=EPISODE_LIMIT):
    """从用户历史 + 运行结果 state.json 提取 Episode（问题/追问/检索词/文献标题）。"""
    records = _done_records(username)
    eps = []
    for r in records[:limit]:
        folder = str(r.get("folder") or "")
        sj = os.path.join(folder, "state.json")
        if not os.path.isfile(sj):
            continue
        try:
            with io.open(sj, encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            continue
        q = str(st.get("question") or r.get("question") or "").strip()
        if not q:
            continue
        kt = st.get("knowledge_tree") or {}
        keywords, papers = [], []
        for sp in kt.get("sub_problems") or []:
            if not isinstance(sp, dict):
                continue
            for kw in sp.get("search_keywords") or []:
                if kw:
                    keywords.append(str(kw))
            for p in sp.get("papers") or []:
                if isinstance(p, dict) and str(p.get("标题") or "").strip():
                    papers.append(str(p["标题"]).strip())
        eps.append({
            "run_id": r.get("run_id"),
            "ts": r.get("started") or 0,
            "question": q,
            "clarify": _read_clarify(r.get("run_id")),
            "keywords": keywords[:30],
            "papers": papers[:12],
        })
    eps.sort(key=lambda e: e.get("ts") or 0)
    return eps


def refresh_episodes_file(username, limit=EPISODE_LIMIT):
    """把 collect_episodes 落盘为 users/<用户名>/episodes.jsonl（Zep Episode 兼容格式）。"""
    try:
        eps = collect_episodes(username, limit=limit)
        d = os.path.join(USERS_ROOT, username)
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, "episodes.jsonl"), "w", encoding="utf-8") as f:
            for e in eps:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _digest(episodes, max_chars=DIGEST_CHARS):
    """把 Episode 列表压缩成 LLM 可读的摘要。"""
    parts = []
    for e in episodes[-12:]:
        parts.append("问题：%s" % str(e.get("question") or "")[:300])
        for x in e.get("clarify") or []:
            if x.get("a"):
                parts.append("  追问：%s → %s" % (str(x.get("q") or "")[:80], str(x.get("a"))[:150]))
        kws = (e.get("keywords") or [])[:8]
        if kws:
            parts.append("  检索词：%s" % "、".join(str(k) for k in kws)[:300])
        ps = (e.get("papers") or [])[:5]
        if ps:
            parts.append("  文献：%s" % "；".join(str(p) for p in ps)[:400])
    out = "\n".join(parts)
    return out[:max_chars]


PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string",
                    "examples": ["以材料化学（钙钛矿太阳能电池）为主，近期转向高温超导机理研究"]},
        "confidence": {"type": "number", "examples": [0.72]},
        "disciplines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "discipline": {"type": "string", "examples": ["化学"]},
                    "weight": {"type": "number", "examples": [0.6]},
                    "subfields": {"type": "array", "items": {"type": "string"},
                                  "examples": ["材料化学"]},
                    "topics": {"type": "array", "items": {"type": "string"},
                               "examples": ["钙钛矿太阳能电池"]},
                    "methods": {"type": "array", "items": {"type": "string"},
                                "examples": ["第一性原理计算 (DFT)"]},
                },
                "required": ["discipline", "weight"],
            },
        },
        "evidence": {"type": "array", "items": {"type": "string"},
                     "examples": ["问题“钙钛矿太阳能电池稳定性”+ 检索词 perovskite 等，显示材料化学方向"]},
    },
    "required": ["summary", "confidence", "disciplines", "evidence"],
}

PROFILE_SYSTEM = """你是一名科研情报分析师。根据用户的历史提问记录（问题、追问回答、检索关键词、查阅文献），推断该用户的专业领域画像，输出一个 JSON 对象。
要求：
1. 领域分层：学科(discipline) → 子领域(subfield) → 研究主题(topic) → 研究方法(method)，尽量细，必须从证据中归纳，禁止凭空编造。
2. 每个学科对象必须给出 discipline 和 weight（0~1 占比，可多学科，总和约 1）；subfields / topics / methods 能推断就写（中英均可），确实推断不出可以省略或给空数组，不许编造。
3. confidence：本次推断的整体把握度（0~1，样本越多越可信）。
4. evidence：2~5 条具体依据（引用是哪条问题/检索词/文献得出的判断）。
5. summary：一句话概括画像，例如「以 XX 为主，近期转向 YY」。
顶层字段 summary / confidence / disciplines / evidence 必须全部存在，disciplines 与 evidence 不许为空数组。"""


def _zep_profile(username, episodes):
    """Zep Cloud 动态知识图谱后端（可插拔）。
    当前为接口占位：未配置 ZEP_API_KEY 一律返回 None（自动落回 LLM）。
    后续接入：把 episodes 灌入 Zep Cloud (api.getzep.com) 的 GraphQL addMemory，
    再用 searchMemory 聚合用户实体/关系生成画像；任何异常返回 None 走兜底。
    """
    key = (os.getenv("ZEP_API_KEY") or "").strip()
    if not key:
        return None
    return None  # TODO: Zep Cloud GraphQL 接入；未完成前安全走 LLM


def get_cached_profile(username):
    """读取上次生成的画像缓存（含 samples / backend / updated_at）。"""
    try:
        fp = os.path.join(USERS_ROOT, username, "profile.json")
        with io.open(fp, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_profile(username, profile, backend, samples):
    try:
        d = os.path.join(USERS_ROOT, username)
        os.makedirs(d, exist_ok=True)
        with io.open(os.path.join(d, "profile.json"), "w", encoding="utf-8") as f:
            json.dump({"profile": profile, "backend": backend, "samples": samples,
                       "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")},
                      f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def build_profile(username):
    """LLM 版画像（含 Zep 可插拔）。样本不足/失败一律 ready=False，不抛异常。"""
    done = _done_records(username)
    samples = len(done)
    if samples < MIN_SAMPLES:
        return {"ready": False, "need": MIN_SAMPLES - samples, "samples": samples,
                "reason": "样本不足", "profile": None, "backend": None, "updated_at": None}
    refresh_episodes_file(username)
    eps = collect_episodes(username)
    if not eps:
        return {"ready": False, "need": MIN_SAMPLES, "samples": samples,
                "reason": "暂无可用运行数据", "profile": None, "backend": None, "updated_at": None}
    digest = _digest(eps)

    backend = (os.getenv("PROFILE_BACKEND") or "llm").strip().lower()
    if backend == "zep":
        prof = _zep_profile(username, eps)
        if prof:
            _save_profile(username, prof, "zep", samples)
            return {"ready": True, "profile": prof, "backend": "zep", "samples": samples,
                    "updated_at": _cache_time(username)}
        # Zep 不可用 → 落回 LLM

    try:
        sys.path.insert(0, SRC)
        import llm_client
        obj = llm_client.json_chat(
            "请分析以下用户历史提问记录，输出该用户的专业领域画像 JSON：\n\n" + digest,
            system=PROFILE_SYSTEM, schema=PROFILE_SCHEMA)
    except Exception as e:
        return {"ready": False, "samples": samples, "reason": "画像生成失败：%s" % e,
                "profile": None, "backend": None, "updated_at": None}

    profile = {"summary": obj.get("summary"), "confidence": obj.get("confidence"),
               "disciplines": obj.get("disciplines"), "evidence": obj.get("evidence")}
    _save_profile(username, profile, "llm", samples)
    return {"ready": True, "profile": profile, "backend": "llm", "samples": samples,
            "updated_at": _cache_time(username)}


def _cache_time(username):
    c = get_cached_profile(username)
    return (c or {}).get("updated_at")


def get_profile_for_api(username, force=False):
    """API 入口：样本数没变且已有缓存 → 直接返回缓存（不烧 token）。"""
    done = _done_records(username)
    samples = len(done)
    cache = get_cached_profile(username)
    if cache and cache.get("profile") and cache.get("samples") == samples and not force:
        return {"ready": True, "profile": cache.get("profile"), "backend": cache.get("backend"),
                "samples": samples, "updated_at": cache.get("updated_at"), "cached": True}
    return build_profile(username)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="生成某用户画像")
    ap.add_argument("username", nargs="?", default="guest")
    ap.add_argument("--force", action="store_true", help="忽略缓存强制重算")
    a = ap.parse_args()
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    r = build_profile(a.username) if a.force else get_profile_for_api(a.username, force=a.force)
    print(json.dumps(r, ensure_ascii=False, indent=2))
