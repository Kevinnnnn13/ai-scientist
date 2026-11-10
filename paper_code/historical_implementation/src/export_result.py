# -*- coding: utf-8 -*-
"""把一次运行的生成结果导出为可分享的报告（Markdown + 自包含 HTML）。

用法（在 ai_scientist 目录下运行）：
  python src/export_result.py                  # 自动导出最近一次运行
  python src/export_result.py --list           # 列出最近 15 次运行
  python src/export_result.py 运行262          # 按名称片段匹配导出
  python src/export_result.py <完整路径>       # 按完整路径导出
  python src/export_result.py --latest 3       # 导出最近 3 次
  python src/export_result.py --no-plot        # 不带分数曲线图

输出（在对应运行目录内）：
  结果报告_<运行编号>.md    普通 Markdown，方便直接转发
  结果报告_<运行编号>.html  自包含网页：内嵌分数曲线，浏览器打开
                            Ctrl+P 即可另存为 PDF 发给同学
"""
import argparse
import base64
import html
import io
import json
import os
import sys

# -*- coding: utf-8 -*-
"""LaTeX -> 可读 Unicode 文本转换器（供 export_result.py 使用）。"""
import re

_LATEX_SYMBOLS = {
    "alpha": "α", "beta": "β", "gamma": "γ", "delta": "δ", "epsilon": "ε",
    "varepsilon": "ε", "zeta": "ζ", "eta": "η", "theta": "θ", "vartheta": "ϑ",
    "iota": "ι", "kappa": "κ", "lambda": "λ", "mu": "μ", "nu": "ν", "xi": "ξ",
    "omicron": "ο", "pi": "π", "varpi": "ϖ", "rho": "ρ", "sigma": "σ",
    "varsigma": "ς", "tau": "τ", "upsilon": "υ", "phi": "φ", "varphi": "φ",
    "chi": "χ", "psi": "ψ", "omega": "ω",
    "Gamma": "Γ", "Delta": "Δ", "Theta": "Θ", "Lambda": "Λ", "Xi": "Ξ",
    "Pi": "Π", "Sigma": "Σ", "Upsilon": "Υ", "Phi": "Φ", "Psi": "Ψ", "Omega": "Ω",
    "infty": "∞", "partial": "∂", "nabla": "∇", "propto": "∝", "hbar": "ℏ",
    "pm": "±", "mp": "∓", "times": "×", "div": "÷", "cdot": "·", "ast": "∗",
    "leq": "≤", "geq": "≥", "le": "≤", "ge": "≥", "neq": "≠", "ne": "≠",
    "ll": "≪", "gg": "≫", "approx": "≈", "simeq": "≃", "sim": "∼", "equiv": "≡",
    "cong": "≅", "in": "∈", "notin": "∉", "ni": "∋", "subset": "⊂", "supset": "⊃",
    "subseteq": "⊆", "supseteq": "⊇", "cup": "∪", "cap": "∩", "forall": "∀",
    "exists": "∃", "nexists": "∄", "neg": "¬", "land": "∧", "lor": "∨",
    "emptyset": "∅", "circ": "∘", "dagger": "†", "ddagger": "‡", "bullet": "•",
    "prime": "′", "degree": "°", "ell": "ℓ",
    "to": "→", "rightarrow": "→", "leftarrow": "←", "mapsto": "↦",
    "Rightarrow": "⇒", "Leftarrow": "⇐", "leftrightarrow": "↔",
    "uparrow": "↑", "downarrow": "↓", "longrightarrow": "→",
    "int": "∫", "oint": "∮", "iint": "∬", "iiint": "∭",
    "sum": "Σ", "prod": "∏", "bigcup": "⋃", "bigcap": "⋂", "lim": "lim",
    "dots": "…", "ldots": "…", "cdots": "…", "vdots": "⋮", "ddots": "⋱",
    "langle": "⟨", "rangle": "⟩", "lfloor": "⌊", "rfloor": "⌋",
    "lceil": "⌈", "rceil": "⌉", "parallel": "∥", "perp": "⊥",
}
_SUB_MAP = {"0": "₀", "1": "₁", "2": "₂", "3": "₃", "4": "₄", "5": "₅", "6": "₆", "7": "₇", "8": "₈", "9": "₉",
            "+": "₊", "-": "₋", "=": "₌", "(": "₍", ")": "₎"}
_SUB_LETTERS = {"a": "ₐ", "e": "ₑ", "h": "ₕ", "i": "ᵢ", "j": "ⱼ", "k": "ₖ", "l": "ₗ", "m": "ₘ",
                "n": "ₙ", "o": "ₒ", "p": "ₚ", "r": "ᵣ", "s": "ₛ", "t": "ₜ", "u": "ᵤ", "v": "ᵥ", "x": "ₓ"}
_SUP_MAP = {"0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴", "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
            "+": "⁺", "-": "⁻", "=": "⁼", "(": "⁽", ")": "⁾"}
_SUP_LETTERS = {"a": "ᵃ", "b": "ᵇ", "c": "ᶜ", "d": "ᵈ", "e": "ᵉ", "f": "ᶠ", "g": "ᵍ", "h": "ʰ",
                "i": "ⁱ", "j": "ʲ", "k": "ᵏ", "l": "ˡ", "m": "ᵐ", "n": "ⁿ", "o": "ᵒ", "p": "ᵖ",
                "r": "ʳ", "s": "ˢ", "t": "ᵗ", "u": "ᵘ", "v": "ᵛ", "w": "ʷ", "x": "ˣ", "y": "ʸ", "z": "ᶻ"}
_SYMBOL_RE = re.compile(r"\\(%s)(?![a-zA-Z])" % "|".join(sorted(_LATEX_SYMBOLS, key=len, reverse=True)))
_TEXTCMD = ("text", "mathrm", "mathbf", "boldsymbol", "bm", "mathit", "operatorname",
            "textrm", "textbf", "emph", "it", "sf", "tt", "mathcal", "mathbb", "mathfrak")


def _latex_script(content, kind):
    if not content:
        return ""
    mapping = dict(_SUB_MAP)
    mapping.update(_SUB_LETTERS)
    prefix = "_"
    if kind == "sup":
        mapping = dict(_SUP_MAP)
        mapping.update(_SUP_LETTERS)
        prefix = "^"
    if all(ch in mapping for ch in content):
        return "".join(mapping[ch] for ch in content)
    if re.fullmatch(r"[A-Za-z0-9_.+\-]+", content):
        return prefix + content
    return prefix + "(" + content + ")"


def _latex_frac(m):
    num = m.group(1).strip()
    den = m.group(2).strip()
    simple = lambda t: bool(re.fullmatch(r"[A-Za-z0-9_.+\-^()/]+", t))
    num = num if simple(num) else "(" + num + ")"
    den = den if simple(den) else "(" + den + ")"
    return num + "/" + den


def _latex_convert_frag(s):
    for cmd in _TEXTCMD:
        s = re.sub(r"\\%s\s*\{([^{}]*)\}" % cmd, r"\1", s)
    s = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", _latex_frac, s)
    s = re.sub(r"\\sqrt(?:\[([^\]]*)\])?\s*\{([^{}]*)\}",
               lambda m: ("√" + (m.group(1) or "")) + "(" + m.group(2) + ")" if m.group(2) else "", s)
    for cmd, comb in (("overline", "\u0305"), ("bar", "\u0304"), ("hat", "\u0302"), ("tilde", "\u0303")):
        s = re.sub(r"\\%s\s*\{([^{}]*)\}" % cmd, lambda m, c=comb: m.group(1) + c, s)
    s = re.sub(r"\\left|\\right|\\big[lr]?|\\Big[lr]?|\\bigg[lr]?|\\Bigg[lr]?", "", s)
    s = _SYMBOL_RE.sub(lambda m: _LATEX_SYMBOLS[m.group(1)], s)
    s = re.sub(r"\^\{([^{}]*)\}", lambda m: _latex_script(m.group(1), "sup"), s)
    s = re.sub(r"_\{([^{}]*)\}", lambda m: _latex_script(m.group(1), "sub"), s)
    s = re.sub(r"\^([0-9a-zA-Z])(?![0-9a-zA-Z])", lambda m: _latex_script(m.group(1), "sup"), s)
    s = re.sub(r"_([0-9a-zA-Z])(?![0-9a-zA-Z])", lambda m: _latex_script(m.group(1), "sub"), s)
    s = s.replace("''", "″").replace("'", "′")
    s = re.sub(r"\\[,;:!]|\\quad|\\qquad|\\;|\\:|\\ ", " ", s)
    s = s.replace("\\\\", " ")
    s = re.sub(r"\\(?:displaystyle|textstyle|limits|nolimits|phantom)\b", "", s)
    s = re.sub(r"\\[a-zA-Z]+\*?", "", s)
    s = s.replace("{", "(").replace("}", ")")
    s = s.replace("~", " ")
    s = re.sub(r" {2,}", " ", s)
    return s.strip()


def latex_to_unicode(text):
    """把文本中的 LaTeX 数学公式转为可读 Unicode 文本。"""
    if not text:
        return text
    s = text
    s = re.sub(r"\\\(\s*(.*?)\s*\\\)", lambda m: _latex_convert_frag(m.group(1)), s, flags=re.S)
    s = re.sub(r"\\\[\s*(.*?)\s*\\\]", lambda m: _latex_convert_frag(m.group(1)), s, flags=re.S)
    s = re.sub(r"\$\$(.*?)\$\$", lambda m: _latex_convert_frag(m.group(1)), s, flags=re.S)
    s = re.sub(r"(?<!\$)\$(?!\$)([^$\n]+?)(?<!\$)\$(?!\$)", lambda m: _latex_convert_frag(m.group(1)), s)
    s = _latex_convert_frag(s)
    return s

try:
    import markdown as md
    HAS_MD = True
except Exception:
    HAS_MD = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except Exception:
    HAS_MPL = False


def find_runs(base):
    """返回 [(mtime, path), ...] 按修改时间倒序。"""
    runs = []
    if not os.path.isdir(base):
        return runs
    for day in os.listdir(base):
        daydir = os.path.join(base, day)
        if not os.path.isdir(daydir):
            continue
        for name in os.listdir(daydir):
            if not name.startswith("运行"):
                continue
            d = os.path.join(daydir, name)
            if os.path.isdir(d) and os.path.isfile(os.path.join(d, "state.json")):
                try:
                    runs.append((os.path.getmtime(d), d))
                except OSError:
                    continue
    runs.sort(key=lambda x: x[0], reverse=True)
    return runs


def resolve_target(base, arg, latest_n):
    runs = find_runs(base)
    if not runs:
        sys.exit("未找到任何运行目录（生成日志为空？）")
    if arg:
        low = arg.lower()
        hits = [p for _, p in runs if low in os.path.basename(p).lower()]
        if not hits:
            sys.exit("未找到名称包含 %r 的运行目录，可用 --list 查看。" % arg)
        return hits[:1]
    if latest_n:
        return [p for _, p in runs[:latest_n]]
    return [runs[0][1]]


def read_text(path):
    try:
        with io.open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def load_state(run_dir):
    p = os.path.join(run_dir, "state.json")
    if not os.path.isfile(p):
        sys.exit("缺少 state.json（运行可能未完成）：" + run_dir)
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def md_section(text, heading):
    """取 markdown 文本中 '## <heading>' 之后到下一个 '## ' 之前的内容。"""
    marker = "## " + heading
    i = text.find(marker)
    if i < 0:
        return ""
    j = text.find("\n## ", i + len(marker))
    return text[i: j if j > 0 else len(text)].strip()


def fmt_cny(v):
    try:
        return "¥%.4f" % float(v)
    except Exception:
        return str(v)


def plot_scores(score_history, target=None):
    """生成分数变化折线图，返回 base64 PNG（无数据返回 None）。"""
    if not HAS_MPL or not score_history:
        return None
    rounds = [r.get("round") or i + 1 for i, r in enumerate(score_history)]
    hyp = [r.get("hypothesis_score") for r in score_history]
    dat = [r.get("data_score") for r in score_history]
    fig, ax = plt.subplots(figsize=(7.6, 3.2), dpi=150)
    ax.plot(rounds, hyp, "o-", color="#0e7c86", lw=2, label="Hypothesis")
    ax.plot(rounds, dat, "s-", color="#e08e0b", lw=2, label="Data")
    if target:
        try:
            ax.axhline(float(target), color="#888", ls="--", lw=1, label="Target %s" % target)
        except Exception:
            pass
    ax.set_xlabel("Round")
    ax.set_ylabel("Score")
    ax.set_ylim(0, 100)
    ax.set_yticks(range(0, 101, 10))
    ax.legend(loc="lower right", fontsize=9)
    ax.grid(alpha=0.25)
    ax.set_title("Score Progression Across Review Rounds", fontsize=11)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")

def collect(run_dir, with_plot=True):
    st = load_state(run_dir)
    no = os.path.basename(run_dir)
    question = str(st.get("question") or "").strip()
    quality = st.get("quality_target") or ""
    status = st.get("status") or ""
    rounds = st.get("rounds")
    hyp_score = st.get("hypothesis_score")
    data_score = st.get("data_score")
    best = latex_to_unicode(str(st.get("best_hypothesis") or st.get("hypothesis") or "").strip())
    score_history = st.get("score_history") or []

    doc1 = latex_to_unicode(read_text(os.path.join(run_dir, "01_知识整合.md")))
    doc2 = latex_to_unicode(read_text(os.path.join(run_dir, "02_假设生成.md")))
    doc3 = ""
    for fn in os.listdir(run_dir):
        if fn.startswith("03_") and fn.endswith(".md"):
            doc3 = latex_to_unicode(read_text(os.path.join(run_dir, fn)))
            break

    gaps = md_section(doc2, "研究缺口")
    if not gaps:
        g = st.get("gap")
        if isinstance(g, str) and g.strip():
            gaps = g.strip()
        elif isinstance(g, (list, dict)):
            gaps = json.dumps(g, ensure_ascii=False, indent=2)
    # md_section 返回的文本从 '## 研究缺口' 标题开始（含标题本身），去掉开头标题行，
    # 避免 render_md / render_html 再输出一次 '## 研究缺口' 造成标题重复。
    if gaps:
        _gaps_lines = gaps.splitlines()
        while _gaps_lines and _gaps_lines[0].strip().startswith("#") and "研究缺口" in _gaps_lines[0]:
            _gaps_lines.pop(0)
        gaps = "\n".join(_gaps_lines).strip()
    gaps = latex_to_unicode(gaps)

    usage = st.get("api_usage") or {}
    cost = fmt_cny(st.get("api_cost_cny"))
    tokens = 0
    for k in ("prompt_tokens", "completion_tokens"):
        try:
            tokens += int(usage.get(k) or 0)
        except Exception:
            pass

    plot_b64 = plot_scores(score_history, target=quality) if with_plot else None
    # 一致性校验：假设↔缺口编号映射（自动纠正）+ 文献术语一致性（2026-08-28）
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from consistency_check import run_checks
        best, findings = run_checks(doc1, gaps, best, doc3)
    except Exception:
        findings = []
    return {
        "no": no, "question": question, "quality": quality, "status": status,
        "rounds": rounds, "hyp_score": hyp_score, "data_score": data_score,
        "best": best, "score_history": score_history, "doc1": doc1,
        "gaps": gaps, "doc3": doc3, "cost": cost, "tokens": tokens,
        "calls": usage.get("calls"), "plot_b64": plot_b64,
        "bottleneck": st.get("bottleneck"), "search_exhausted": bool(st.get("search_exhausted")),
        "run_dir": run_dir, "consistency_findings": findings,
    }


def esc(s):
    return html.escape(str(s or ""))


def score_table(score_history):
    if not score_history:
        return ""
    rows = []
    for r in score_history:
        rows.append("| %s | %s | %s |" % (r.get("round"), r.get("hypothesis_score"), r.get("data_score")))
    return "| 轮次 | 假设分 | 数据分 |\n| --- | --- | --- |\n" + "\n".join(rows) + "\n"


def low_data_note_md(score, bottleneck=None, search_exhausted=False):
    """数据分极低（<=65）时附加的读者说明；否则返回空串。"""
    if score is None:
        return ""
    try:
        fscore = float(score)
    except Exception:
        return ""
    if fscore > 65:
        return ""
    s = int(fscore) if fscore == int(fscore) else ("%.1f" % fscore)
    exhausted = "（本轮文献检索已确认无更多可用直接来源）" if search_exhausted else ""
    lines = [
        "## 关于数据分较低（%s 分）的说明" % s,
        "",
        "本报告的数据分（data_score）为 %s/100，属于极低分区。低数据分**不代表假设本身错误**，通常反映「数据/证据支撑」维度可用的直接文献与数据很少，常见原因与解读如下：%s" % (s, exhausted),
        "",
        "- **冷门/小众研究领域**：该问题方向的公开高质量文献与实验数据稀少（例如交叉 Cannizzaro 反应这类具体课题，直接相关的双醛竞争数据很少），评审在 evidence 维度缺少可引用的实证链条，得分自然偏低。",
        "- **知识树存在 ◇争议 / ✗缺口**：当核心知识节点缺乏直接文献支撑时，证据基础被判定为 has_gap_or_debate（带缺口），数据分反映的是「以缺口支撑假设」的状态，而非假设有误。",
        "- **开放性假设的正常表现**：在证据稀缺的领域，系统产出的往往是可检验的开放性假设（open hypothesis），其价值在于给出清晰的验证路径，而不是已有大量数据背书。",
        "",
        "建议解读：**高假设分 + 低数据分** 恰恰说明「假设新颖、证据待补」——后续补充针对性实验/数据即可提升证据链强度；若假设分也低，则说明假设本身还需迭代打磨。",
        "",
        "（本说明由系统按分数档位自动附加，不影响评审与评分本身。）",
    ]
    return "\n".join(lines) + "\n"


def render_md(d):
    lines = []
    lines.append("# AI Scientist · 科学假设生成结果报告\n")
    lines.append("- **运行编号**：%s" % d["no"])
    lines.append("- **研究问题**：%s" % d["question"])
    lines.append("- **目标档位**：%s 分　**状态**：%s　**迭代轮次**：%s" % (d["quality"], d["status"], d["rounds"]))
    lines.append("- **假设分**：%s / 100　**数据分**：%s / 100" % (d["hyp_score"], d["data_score"]))
    if d["cost"]:
        lines.append("- **API 消耗**：%s（%s tokens，%s 次调用）" % (d["cost"], format(d["tokens"], ","), d["calls"]))
    lines.append("")
    low_note = low_data_note_md(d["data_score"], d.get("bottleneck"), d.get("search_exhausted"))
    if low_note:
        lines.append(low_note)
        lines.append("")
    if d["doc1"]:
        lines.append("## 知识整合\n")
        lines.append(d["doc1"])
        lines.append("")
    if d["gaps"]:
        lines.append("## 研究缺口\n")
        lines.append(d["gaps"])
        lines.append("")
    if d["best"]:
        lines.append("## 最佳假设\n")
        lines.append(d["best"])
        lines.append("")
    if d["score_history"]:
        lines.append("## 分数变化\n")
        lines.append(score_table(d["score_history"]))
        lines.append("")
    if d["doc3"]:
        lines.append("## 可验证性验证\n")
        lines.append(d["doc3"])
        lines.append("")
    if d.get("consistency_findings"):
        lines.append("## 一致性校验说明（系统自动）\n")
        for f in d["consistency_findings"]:
            lines.append("- **%s**：%s" % ("已自动纠正" if f.get("level") == "fix" else "请核对", f.get("detail")))
        lines.append("")
    lines.append("---")
    lines.append("*由 AI Scientist 自动生成 · %s · 来源目录：`%s`*" % (d["no"], d["run_dir"]))
    return "\n".join(lines)


def render_html(d):
    if HAS_MD:
        def to_html(t):
            return md.markdown(str(t or ""), extensions=["extra", "nl2br", "sane_lists"])
    else:
        def to_html(t):
            return "<p>" + esc(t).replace("\n", "<br>") + "</p>"

    score_cells = ""
    if d["score_history"]:
        trs = "".join(
            "<tr><td>%s</td><td>%s</td><td>%s</td></tr>" % (r.get("round"), r.get("hypothesis_score"), r.get("data_score"))
            for r in d["score_history"]
        )
        plot_img = ('<img class="plot" src="data:image/png;base64,%s" alt="score progression">' % d["plot_b64"]) if d["plot_b64"] else ""
        score_cells = """
        <div class="card">
          <h2>分数变化</h2>
          %s
          <table><tr><th>轮次</th><th>假设分</th><th>数据分</th></tr>%s</table>
        </div>""" % (plot_img, trs)

    gaps_html = to_html(d["gaps"]) if d["gaps"] else ""
    doc3_html = to_html(d["doc3"]) if d["doc3"] else ""
    usage_line = ""
    if d["cost"]:
        usage_line = ('<div class="meta-chip">本次 API 消耗 <b>%s</b> · %s tokens · %s 次调用</div>'
                      % (d["cost"], format(d["tokens"], ","), d["calls"]))

    best_html = to_html(d["best"]) if d["best"] else '<p>（运行未完成，暂无最终假设）</p>'
    doc1_html = to_html(d["doc1"]) if d["doc1"] else ""
    findings_html = ""
    if d.get("consistency_findings"):
        _items = "".join('<li><b>%s</b>：%s</li>' % ("已自动纠正" if f.get("level") == "fix" else "请核对", esc(f.get("detail")))
                         for f in d["consistency_findings"])
        findings_html = '<div class="card" style="border-left:4px solid #e08e0b"><h2>一致性校验说明（系统自动）</h2><ul>%s</ul></div>' % _items
    low_note_md = low_data_note_md(d["data_score"], d.get("bottleneck"), d.get("search_exhausted"))
    low_note_html = '<div class="card warn-note">' + to_html(low_note_md) + '</div>' if low_note_md else "" ""

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Scientist 结果报告 · %s</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #f4f7fb; color: #1f2733; font-family: "Segoe UI", "Microsoft YaHei", sans-serif; line-height: 1.75; padding: 28px 14px 60px; }
  .wrap { max-width: 860px; margin: 0 auto; }
  h1 { font-size: 26px; color: #0e4f57; }
  h2 { font-size: 19px; color: #0e4f57; margin: 18px 0 10px; border-left: 4px solid #00b8d4; padding-left: 10px; }
  h3 { font-size: 16px; margin-top: 14px; }
  .card { background: #fff; border: 1px solid #e3eaf2; border-radius: 12px; padding: 18px 22px; margin-top: 16px; box-shadow: 0 2px 8px rgba(14,79,87,.06); }
  .hero { background: linear-gradient(135deg, #0e4f57, #00b8d4); color: #fff; border-radius: 12px; padding: 22px 26px; }
  .hero h1 { color: #fff; font-size: 24px; }
  .hero .sub { margin-top: 6px; font-size: 14px; opacity: .9; }
  .scores { display: flex; gap: 14px; margin-top: 14px; flex-wrap: wrap; }
  .score-box { background: #fff; border: 1px solid #e3eaf2; border-radius: 10px; padding: 12px 22px; text-align: center; min-width: 120px; }
  .score-box .num { font-size: 34px; font-weight: 800; color: #0e4f57; }
  .score-box .num.hyp { color: #0e7c86; }
  .score-box .num.data { color: #e08e0b; }
  .score-box .lbl { font-size: 13px; color: #7a8794; }
  .meta-chip { display: inline-block; background: #e8f6f8; color: #0e4f57; border-radius: 20px; padding: 6px 16px; font-size: 14px; margin-top: 12px; }
  .question { font-size: 16px; font-weight: 600; margin-top: 6px; }
  img.plot { width: 100%%; border-radius: 8px; margin: 10px 0; }
  table { border-collapse: collapse; width: 100%%; margin-top: 10px; }
  th, td { border: 1px solid #e3eaf2; padding: 6px 12px; text-align: center; font-size: 14px; }
  th { background: #eef7f8; color: #0e4f57; }
  code { background: #eef1f5; border-radius: 4px; padding: 1px 6px; font-size: 13px; }
  pre { background: #f6f8fa; border: 1px solid #e3eaf2; border-radius: 8px; padding: 12px; overflow-x: auto; }
  blockquote { border-left: 4px solid #00b8d4; padding: 4px 14px; color: #445; background: #f7fbfc; }
  .warn-note { border-left: 4px solid #e08e0b; background: #fff8f0; }
  .foot { color: #7a8794; font-size: 12px; margin-top: 24px; text-align: center; }
  @media print { body { background: #fff; padding: 0; } .card { box-shadow: none; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <h1>AI Scientist · 科学假设生成结果报告</h1>
    <div class="sub">%s · 目标 %s 分 · 状态 %s · 迭代 %s 轮</div>
    <div class="scores">
      <div class="score-box"><div class="num hyp">%s</div><div class="lbl">假设分</div></div>
      <div class="score-box"><div class="num data">%s</div><div class="lbl">数据分</div></div>
      <div class="score-box"><div class="num">%s</div><div class="lbl">迭代轮次</div></div>
    </div>
    %s
  </div>

  <div class="card">
    <h2>研究问题</h2>
    <div class="question">%s</div>
  </div>

  %s

  %s
  %s

  <div class="card">
    <h2>最佳假设</h2>
    %s
  </div>

  %s

  %s

  %s

  <div class="foot">由 AI Scientist 自动生成 · 来源目录：%s</div>
</div>
</body>
</html>""" % (
        esc(d["no"]), esc(d["no"]), esc(d["quality"]), esc(d["status"]), esc(d["rounds"]),
        esc(d["hyp_score"]), esc(d["data_score"]), esc(d["rounds"]), usage_line,
        esc(d["question"]), low_note_html,
        ('<div class="card"><h2>知识整合</h2>%s</div>' % doc1_html) if d["doc1"] else "",
        ('<div class="card"><h2>研究缺口</h2>%s</div>' % gaps_html) if gaps_html else "",
        best_html, score_cells,
        ('<div class="card"><h2>可验证性验证</h2>%s</div>' % doc3_html) if doc3_html else "",
        findings_html, esc(d["run_dir"]),
    )


def main():
    ap = argparse.ArgumentParser(description="导出 AI Scientist 运行结果为可分享报告")
    ap.add_argument("target", nargs="?", default="", help="运行目录名（片段匹配）或完整路径")
    ap.add_argument("--list", action="store_true", help="列出最近 15 次运行")
    ap.add_argument("--latest", type=int, default=0, help="导出最近 N 次（默认 1）")
    ap.add_argument("--no-plot", action="store_true", help="不带分数曲线图")
    args = ap.parse_args()

    base = os.path.join(os.path.expanduser("~"), "Desktop", "26暑假", "27日", "生成日志")
    if args.list:
        runs = find_runs(base)
        if not runs:
            print("未找到任何运行目录。")
            return
        print("最近 %d 次运行：" % min(15, len(runs)))
        for _, p in runs[:15]:
            st = load_state(p)
            q = str(st.get("question") or "")
            q = q if len(q) <= 70 else q[:67] + "..."
            print("  %s\n    分数 %s/%s · %s" % (os.path.basename(p), st.get("hypothesis_score"), st.get("data_score"), q))
        return

    targets = resolve_target(base, args.target, args.latest)
    for t in targets:
        d = collect(t, with_plot=not args.no_plot)
        md_text = render_md(d)
        html_text = render_html(d)
        md_path = os.path.join(t, "结果报告_%s.md" % d["no"])
        html_path = os.path.join(t, "结果报告_%s.html" % d["no"])
        with io.open(md_path, "w", encoding="utf-8") as f:
            f.write(md_text)
        with io.open(html_path, "w", encoding="utf-8") as f:
            f.write(html_text)
        print("已导出：%s" % d["no"])
        print("  Markdown：%s" % md_path)
        print("  HTML（打印可存 PDF）：%s" % html_path)
        if d["plot_b64"]:
            print("  分数曲线：内嵌（%s 轮）" % d["rounds"])


if __name__ == "__main__":
    main()
