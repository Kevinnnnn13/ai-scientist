"""news_digest.py：每日新闻精炼（配置驱动版）

流程：按 config.json 的关键词+权重搜索 → DeepSeek(json_chat) 压成精选 JSON → 存 data/news_digest.json

用法：
    python src/news_digest.py
    python src/news_digest.py "自定义主题"   （可选：命令行主题覆盖 config 的领域）
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from config import load_config, build_search_plan
from llm_client import json_chat
from schemas import NEWS_SCHEMA
from search_web import search_web

DIGEST_SYSTEM = (
    "你是一个严谨的新闻编辑。输出 JSON 时你必须严格遵守以下纪律：\n"
    "1. 只输出一个 JSON 对象，不要输出任何解释；\n"
    "2. 字段名严格等于要求中给出的；\n"
    "3. 新闻列表最多 10 条，每条必须包含标题、一句话摘要、为什么值得关注、来源链接；\n"
    "4. 禁止编造：摘要和链接只能基于我提供的原始材料；\n"
    "5. 为什么值得关注：站在大学生读者角度，讲清楚这条新闻为什么与他有关。\n"
)

PROMPT_TEMPLATE = """今天是 {today}，主题：{topic}。

下面是联网搜索到的原始材料（已过滤，只保留最近 48 小时内的新闻，可能重复、含噪音）：
{raw}

请筛选出最值得关注、互不重复的新闻，输出结构化 JSON，结构要求：
{preview}

额外要求：
1. 新闻列表最多 10 条；若有效材料不足 10 条，有几条写几条；
2. 一句话摘要不超过 40 字；
3. 来源链接必须来自原始材料；
4. 优先选择发布时间最新的新闻。"""


def schema_preview(schema):
    lines = []
    for name, spec in schema["properties"].items():
        lines.append(f'- "{name}"（{spec.get("type")}）')
        if spec.get("type") == "array":
            item = spec.get("items", {})
            lines.append(f'  数组元素是对象，必填：{"、".join(item.get("required", []))}')
    return "\n".join(lines)


def is_fresh(r, hours=48):
    """代码层时效校验：发布时间在 hours 小时内才算新鲜（比提示词可靠）"""
    raw = r.get("published_date")
    if not raw:
        return True  # 没有时间戳的保留，宁留勿漏
    try:
        pub = parsedate_to_datetime(raw)
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
    except Exception:
        return True
    return datetime.now(timezone.utc) - pub <= timedelta(hours=hours)


def collect_raw(config, fallback_per_query=5):
    """按 config 的关键词+权重搜索，收集最近 48 小时的原始材料。

    与旧版的区别：旧版写死 3 组关键词（topic/大模型/新闻）；
    现在从 config 拿关键词，并按权重分配每组搜几条（build_search_plan）。
    """
    raw_lines = []
    plan = build_search_plan(config)                # [(关键词, 搜索条数), ...]
    for word, count in plan:
        print(f"→ 搜索：{word}（预算 {count} 条）")
        results = search_web(word, max_results=count, topic="news", days=2)
        hours = config.get("时效小时", 48)
        fresh = [r for r in results if is_fresh(r, hours=hours)]
        print(f"    搜到 {len(results)} 条，保留 {len(fresh)} 条（丢弃 {len(results) - len(fresh)} 条超 {hours}h）")
        for r in fresh:
            raw_lines.append({
                "标题": r.get("title"),
                "摘要": (r.get("content") or "")[:200],
                "链接": r.get("url"),
                "发布时间": r.get("published_date"),
            })
    if not raw_lines:
        print("⚠ 最近 48 小时没搜到新闻，降级：改用不过滤的最新几条，避免下游拿到空材料")
        latest = search_web(plan[0][0], max_results=fallback_per_query, topic="news")
        for r in latest[:3]:
            raw_lines.append({
                "标题": r.get("title"),
                "摘要": (r.get("content") or "")[:200],
                "链接": r.get("url"),
                "发布时间": r.get("published_date"),
            })
    return raw_lines


def main():
    config = load_config()
    # 主题：命令行参数优先，否则用 config 的领域拼"今日要闻"
    topic = sys.argv[1] if len(sys.argv) > 1 else f"{config['领域']}今日要闻"

    raw_list = collect_raw(config)
    raw_text = "\n".join(
        f"- ({r.get('发布时间', '未知')}) {r['标题']} | {r['摘要']} | {r['链接']}"
        for r in raw_list
    )

    prompt = PROMPT_TEMPLATE.format(
        today=date.today().isoformat(),
        topic=topic,
        raw=raw_text,
        preview=schema_preview(NEWS_SCHEMA),
    )
    result = json_chat(prompt, system=DIGEST_SYSTEM, schema=NEWS_SCHEMA)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "news_digest.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已保存到：{out_path}")


if __name__ == "__main__":
    main()
