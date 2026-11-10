# -*- coding: utf-8 -*-
"""Generate a reviewer-friendly, score-blind report from one AI Scientist run.

This report is intended for independent human evaluation. It deliberately
excludes internal scores, review trajectories, raw prompts and system variant
names, so the reviewer judges the submitted research plan rather than the
workflow's self-assessment.
"""

import argparse
import hashlib
import html
import json
import os
import re
import sys


SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

try:
    from export_result import latex_to_unicode
except Exception:
    latex_to_unicode = lambda value: value


def _esc(value):
    return html.escape(str(value or ""))


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _blind_code(run_dir):
    seed = os.path.basename(os.path.normpath(run_dir)).encode("utf-8", errors="ignore")
    return hashlib.sha256(seed).hexdigest()[:8].upper()


def _split_hypothesis_sections(text):
    text = _clean(text)
    labeled_pieces = re.split(
        r"(?=(?:提出依据|预期结果|验证方法|判定标准|文献依据级别|反例条件)[：:])",
        text,
    )
    circle_pieces = re.split(
        r"(?=(?:\*\*[①②③④⑤]|[①②③④⑤]\s*\*\*)[^\n]*\*\*)",
        text,
    )
    pieces = circle_pieces if len(circle_pieces) > len(labeled_pieces) else labeled_pieces

    sections = []
    for piece in pieces:
        piece = piece.strip()
        if not piece:
            continue
        match = re.match(r"^(.*?)[：:]\s*(.*)$", piece, flags=re.S)
        if match and len(match.group(1)) < 48:
            label = re.sub(r"[*＊①②③④⑤\s]+", "", match.group(1)).strip() or "说明"
            body = match.group(2).strip()
        else:
            label = "说明"
            body = piece
        sections.append((label, body))
    return sections


def _parse_hypotheses(best_text):
    chunks = re.split(r"(?=(?:^|\n)\s*#{0,6}\s*\*{0,2}假设\s*\d+)", str(best_text or "").strip())
    hypotheses = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk or not re.match(r"#{0,6}\s*\*{0,2}假设\s*\d+", chunk):
            continue
        title_match = re.match(r"^(?:#{1,6}\s*|\*{0,2})(\*{0,2}假设\s*\d+)[^\n]*", chunk)
        if title_match:
            title = re.sub(r"[*＊#]+", "", title_match.group(1)).strip()
            body = chunk[title_match.end() :].lstrip("\n").strip()
        else:
            title = "研究假设"
            body = chunk
        body = re.split(r"\n\s*(?:✅|是否需要|综上|以上假设|所有假设)", body, maxsplit=1)[0].rstrip()
        hypotheses.append((title, _split_hypothesis_sections(body)))
    return hypotheses


def _references_html(literature, limit=20):
    if not literature:
        return ""
    rows = []
    for idx, paper in enumerate(literature[:limit], 1):
        if isinstance(paper, dict):
            parts = [
                str(paper.get("标题") or paper.get("title") or "").strip(),
                str(paper.get("期刊") or paper.get("journal") or "").strip(),
                str(paper.get("年份") or paper.get("year") or "").strip(),
            ]
            ref = "，".join(x for x in parts if x)
        else:
            ref = str(paper)
        if ref:
            rows.append(f"<li>{_esc(_clean(ref))}</li>")
    if not rows:
        return ""
    return (
        "<h2>来源文献</h2>"
        "<p class='guide'>下列文献由系统检索得到；请根据方案正文判断每条引用是否真正支持相应内容。</p>"
        f"<ol>{''.join(rows)}</ol>"
    )


def _operational_note(state):
    notes = []
    literature = state.get("literature") or []
    if not literature:
        notes.append("本次运行未获得可用的直接文献。")
    if state.get("search_exhausted"):
        notes.append("检索在达到预算后结束，系统未继续补充新文献。")
    frontier_error = state.get("frontier_error")
    if frontier_error:
        notes.append("前沿文献扫描未完成。")
    if not notes:
        notes.append("未记录到检索或运行故障。")
    return "；".join(notes)


def _checklist_html():
    criteria = [
        ("可证伪性", "是否写清楚了什么结果会推翻假设"),
        ("变量和关系", "自变量、因变量、比较条件和预期方向是否清楚"),
        ("方法可行性", "给定资源和条件下，验证方法是否可执行"),
        ("事实依据", "事实性前提是否有来源，来源是否支持这句话"),
        ("已知与猜测", "是否明确区分已经知道的内容和尚未验证的猜测"),
        ("内部一致性", "是否存在未解决的关键矛盾"),
        ("信息完整", "计划必需的信息是否完整"),
    ]
    rows = []
    for idx, (name, guide) in enumerate(criteria, 1):
        rows.append(
            "<tr><td class='num'>{}</td><td><strong>{}</strong><br><span>{}</span></td>"
            "<td class='choice'><label><input type='checkbox'> 通过</label></td>"
            "<td class='choice'><label><input type='checkbox'> 不通过</label></td>"
            "<td class='choice'><label><input type='checkbox'> 无法判断</label></td></tr>".format(
                idx, _esc(name), _esc(guide)
            )
        )
    return (
        "<h2>评审检查表</h2>"
        "<p class='guide'>请逐项判断。任意一项为“不通过”，该计划即记为无效。</p>"
        "<table class='checklist'><thead><tr><th>编号</th><th>检查项</th><th>通过</th>"
        "<th>不通过</th><th>无法判断</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def build_reviewer_html(state, run_dir=None, blind_code=None):
    question = _clean(state.get("question") or "")
    best = latex_to_unicode(state.get("best_hypothesis") or state.get("hypothesis") or "")
    literature = state.get("literature") or []
    hypotheses = _parse_hypotheses(best)
    code = blind_code or _blind_code(run_dir or "")

    cards = []
    for idx, (title, sections) in enumerate(hypotheses, 1):
        fields = []
        for label, body in sections:
            fields.append(
                f"<div class='field'><div class='label'>{_esc(label)}</div>"
                f"<div>{_esc(body)}</div></div>"
            )
        cards.append(f"<section class='hypothesis'><h3>假设 {idx}</h3>{''.join(fields)}</section>")

    if not cards:
        cards = ["<p>未生成可供阅读的完整研究计划。</p>"]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>研究方案阅读版 · {_esc(code)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; color: #202124; margin: 0; background: #f5f7fa; line-height: 1.75; }}
  .page {{ max-width: 900px; margin: 0 auto; padding: 28px 24px 60px; background: #fff; }}
  h1 {{ font-size: 25px; margin: 0 0 6px; }}
  h2 {{ font-size: 19px; margin: 30px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e2e6ea; }}
  h3 {{ font-size: 16px; margin: 0 0 8px; }}
  .meta {{ color: #66707a; font-size: 14px; margin-bottom: 24px; }}
  .question {{ background: #f0f5ff; border-left: 4px solid #2f5aa8; padding: 14px 16px; margin: 12px 0 22px; }}
  .question strong {{ display: block; margin-bottom: 6px; }}
  .notice, .guide {{ color: #66707a; font-size: 13px; }}
  .hypothesis {{ border: 1px solid #e2e6ea; border-radius: 6px; padding: 16px 18px; margin: 14px 0; }}
  .field {{ margin: 10px 0; }}
  .label {{ font-weight: 700; color: #2f5aa8; margin-bottom: 2px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0 20px; }}
  th, td {{ border: 1px solid #dce1e7; padding: 8px 9px; vertical-align: top; text-align: left; }}
  th {{ background: #eef2f6; }}
  .checklist td.num {{ width: 42px; text-align: center; }}
  .checklist .choice {{ width: 86px; text-align: center; }}
  .checklist span {{ display: block; color: #66707a; font-weight: 400; font-size: 13px; }}
  ol {{ padding-left: 24px; }}
  li {{ margin-bottom: 6px; }}
  @media print {{ body {{ background: #fff; }} .page {{ padding: 0; max-width: none; }} }}
</style>
</head>
<body>
<div class="page">
  <h1>研究方案阅读版</h1>
  <div class="meta">样本编号：{_esc(code)}<br>本材料不显示系统内部评分。</div>

  <h2>研究问题</h2>
  <div class="question"><strong>原始问题</strong><div>{_esc(question)}</div></div>
  <p class="notice">请根据问题本身和方案内容判断，不需要评价系统实现。</p>

  <p class="guide">本材料包含 {len(hypotheses)} 个研究假设和 {min(len(literature), 20)} 条来源文献。请重点判断方案是否清楚、可行、有据，并区分已知内容与未经验证的新主张。</p>

  <h2>研究假设</h2>
  {''.join(cards)}

  {_references_html(literature)}

  <h2>运行情况</h2>
  <p>{_esc(_operational_note(state))}</p>

  {_checklist_html()}
</div>
</body>
</html>"""


def build_reviewer_md(state, run_dir=None, blind_code=None):
    question = _clean(state.get("question") or "")
    best = latex_to_unicode(state.get("best_hypothesis") or state.get("hypothesis") or "")
    literature = state.get("literature") or []
    hypotheses = _parse_hypotheses(best)
    code = blind_code or _blind_code(run_dir or "")

    lines = [
        "# 研究方案阅读版",
        "",
        f"- 样本编号：{code}",
        "- 说明：本材料不显示系统内部评分。",
        "",
        "## 研究问题",
        "",
        question,
        "",
        "> 请根据问题本身和方案内容判断，不需要评价系统实现。",
        "",
        f"本材料包含 {len(hypotheses)} 个研究假设和 {min(len(literature), 20)} 条来源文献。",
        "",
        "## 研究假设",
        "",
    ]

    for idx, (title, sections) in enumerate(hypotheses, 1):
        lines.append(f"### 假设 {idx}")
        lines.append("")
        for label, body in sections:
            lines.append(f"**{label}**")
            lines.append("")
            lines.append(body)
            lines.append("")

    lines.append("## 来源文献")
    lines.append("")
    if literature:
        for idx, paper in enumerate(literature[:20], 1):
            if isinstance(paper, dict):
                parts = [
                    str(paper.get("标题") or paper.get("title") or "").strip(),
                    str(paper.get("期刊") or paper.get("journal") or "").strip(),
                    str(paper.get("年份") or paper.get("year") or "").strip(),
                ]
                ref = "，".join(x for x in parts if x)
            else:
                ref = str(paper)
            if ref:
                lines.append(f"{idx}. {_clean(ref)}")
    else:
        lines.append("无可用直接文献。")
    lines.append("")

    lines += [
        "## 运行情况",
        "",
        _operational_note(state),
        "",
        "## 评审检查表",
        "",
        "请逐项判断。任意一项为“不通过”，该计划即记为无效。",
        "",
        "| # | 检查项 | 通过 | 不通过 | 无法判断 |",
        "| --- | --- | --- | --- | --- |",
        "| 1 | 可证伪性：是否写清楚了什么结果会推翻假设 | | | |",
        "| 2 | 变量和关系：自变量、因变量、比较条件和预期方向是否清楚 | | | |",
        "| 3 | 方法可行性：给定资源和条件下，验证方法是否可执行 | | | |",
        "| 4 | 事实依据：事实性前提是否有来源，来源是否支持这句话 | | | |",
        "| 5 | 已知与猜测：是否明确区分已经知道的内容和尚未验证的猜测 | | | |",
        "| 6 | 内部一致性：是否存在未解决的关键矛盾 | | | |",
        "| 7 | 信息完整：计划必需的信息是否完整 | | | |",
        "",
    ]
    return "\n".join(lines)


def write_reviewer_report(run_dir, blind_code=None, as_md=False):
    run_dir = os.path.abspath(os.path.expanduser(run_dir))
    state_path = os.path.join(run_dir, "state.json")
    if not os.path.isfile(state_path):
        raise FileNotFoundError("missing state.json: " + state_path)
    with open(state_path, "r", encoding="utf-8") as f:
        state = json.load(f)

    code = blind_code or _blind_code(run_dir)
    html_text = build_reviewer_html(state, run_dir=run_dir, blind_code=code)
    html_path = os.path.join(run_dir, f"独立评审报告_{code}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_text)

    if as_md:
        md_text = build_reviewer_md(state, run_dir=run_dir, blind_code=code)
        md_path = os.path.join(run_dir, f"独立评审报告_{code}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        return html_path, md_path
    return html_path, None


def main():
    parser = argparse.ArgumentParser(description="Export a score-blind reviewer report.")
    parser.add_argument("run_dir", help="Run directory containing state.json")
    parser.add_argument("--code", default="", help="Optional reviewer blind code")
    parser.add_argument("--md", action="store_true", help="Also export a plain Markdown version")
    args = parser.parse_args()
    html_path, md_path = write_reviewer_report(args.run_dir, blind_code=args.code, as_md=args.md)
    print(html_path)
    if md_path:
        print(md_path)


if __name__ == "__main__":
    main()
