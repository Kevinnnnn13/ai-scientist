# -*- coding: utf-8 -*-
"""报告内容一致性校验（2026-08-28 新增）。

背景：
1. 假设标题里的「对应缺口N」是 LLM 生成的软引用，且缺口列表在多轮间可能被重新分析
   （编号/内容漂移），导致假设引用的编号与报告展示的缺口列表对不上。
2. 同一篇文献在不同段落可能出现术语自相矛盾（如「Ultra-Wide Bandgap」vs「窄禁带体系」）。

提供两道机械校验（在 export_result 出报告时运行，不碰主流程）：
1. 假设↔缺口编号映射：每个假设「对应缺口N」与报告缺口列表逐条做关键词重合度打分；
   错配且高置信时自动纠正编号（标题 + 正文引用 + 分工说明），并在报告末尾附说明。
2. 文献术语一致性：同一篇论文标题多次出现时，检查上下文中的「宽禁带/窄禁带」类术语是否矛盾。

fail-open：解析失败 / 无缺口 / 无假设时静默返回，不阻塞出报告。
"""
import re

_GAP_START = re.compile(r"缺口(\d+)[：:]")
_HYP_HEAD = re.compile(r"^#{1,4}\s*假设([一二三四五六七八九十\d]+)[（(]对应缺口(\d+)")

_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _cn_to_int(s):
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if len(s) == 2 and s[0] == "十":
        return 10 + _CN_NUM.get(s[1], 0)
    if len(s) == 2 and s[1] == "十":
        return _CN_NUM.get(s[0], 0) * 10
    if len(s) == 3 and s[1] == "十":
        return _CN_NUM.get(s[0], 0) * 10 + _CN_NUM.get(s[2], 0)
    return 0


def split_gaps(text):
    """把缺口文本切成 [(编号, 正文块)]。"""
    out = []
    if not text:
        return out
    for p in re.split(r"(?=缺口\d+[：:])", text):
        m = _GAP_START.match(p.strip())
        if m:
            out.append((int(m.group(1)), p.strip()))
    return out


def split_hypotheses(text):
    """把假设文本切成 [{num, cn, claimed, title, start, body}]。"""
    out = []
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        m = _HYP_HEAD.match(ln)
        if m:
            cn, claimed = m.group(1), int(m.group(2))
            out.append({"num": _cn_to_int(cn), "cn": cn, "claimed": claimed,
                        "title": ln, "start": i})
    for j, h in enumerate(out):
        end = out[j + 1]["start"] if j + 1 < len(out) else len(lines)
        h["body"] = "\n".join(lines[h["start"]:end])
    return out


def _shingles(text):
    t = str(text or "").lower()
    out = set()
    for m in re.finditer(r"[a-z][a-z0-9\-]{1,}", t):
        out.add(m.group(0))
    han = re.findall(r"[\u4e00-\u9fff]", t)
    for i in range(len(han) - 1):
        out.add(han[i] + han[i + 1])
    return out


def _overlap(a, b):
    sa, sb = _shingles(a), _shingles(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / min(len(sa), len(sb))


MARGIN = 0.06        # 最佳缺口与声称缺口得分差下限，低于不自动纠正
MIN_ABS = 0.12       # 最佳缺口绝对得分下限，防止对无关缺口瞎纠正
MIN_CLAIM_ABS = 0.22  # 声称缺口自身重合度上限：声称缺口必须弱匹配才自动纠正（防误伤正确引用）
RATIO_MIN = 1.3      # 最佳/声称 得分比下限：最佳必须显著优于声称才改（防「声称分不低、最佳只高一点」误改）


def _theme_of(block):
    """取假设的「①背景依据 + ②明确主张」作为主题（③ 之前），剔除缺口编号元信息。"""
    m = re.search(r"③", block)
    theme = block[:m.start()] if m else block[:500]
    theme = re.sub(r"对应缺口\d+", "", theme)
    theme = re.sub(r"缺口\d+", "", theme)
    return theme


def _score_vs_gap(theme, gap_text):
    """主题 vs 缺口块重合度（缺口编号元信息不计入）。"""
    return _overlap(re.sub(r"缺口\d+", "", theme), re.sub(r"缺口\d+", "", gap_text))


def _idf_scorer(gap_sans):
    """按缺口集合构造 IDF 权重：只在少数缺口出现的稀有词权重大，通用词权重小。"""
    df = {}
    for gb in gap_sans:
        for s in _shingles(gb):
            df[s] = df.get(s, 0) + 1
    n_gap = max(len(gap_sans), 1)

    def _w(s):
        return 1.0 + (n_gap / df[s] if s in df else n_gap)

    def _score(theme, gi):
        ta, ga = _shingles(theme), _shingles(gap_sans[gi])
        if not ga:
            return 0.0
        return sum(_w(s) for s in (ta & ga)) / sum(_w(s) for s in ga)

    return _score


def check_gap_refs(best_text, gaps_text):
    """返回 (修正后的 best_text, findings)。"""
    gaps = split_gaps(gaps_text)
    hyps = split_hypotheses(best_text)
    if not gaps or not hyps:
        return best_text, []
    gap_ids = [g[0] for g in gaps]
    findings = []
    fixes = []  # (cn, claimed, best)
    for h in hyps:
        claimed = h["claimed"]
        if claimed not in gap_ids:
            findings.append({
                "type": "gap_ref", "level": "warn",
                "detail": "假设%s 引用的「缺口%d」在报告缺口列表中不存在（现有：%s），请人工核对"
                          % (h["cn"], claimed, "、".join(str(i) for i in gap_ids))})
            continue
        theme = _theme_of(h["body"])
        gap_sans = [re.sub(r"缺口\d+", "", gbody) for _gid, gbody in gaps]
        _score = _idf_scorer(gap_sans)
        scores = {gid: _score(theme, i) for i, (gid, _gbody) in enumerate(gaps)}
        best_id = max(scores, key=scores.get)
        sc_claim, sc_best = scores[claimed], scores[best_id]
        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        second = ranked[1][1] if len(ranked) > 1 else sc_best
        second_gap = ranked[1][0] if len(ranked) > 1 else best_id
        if (best_id != claimed and (sc_best - sc_claim) >= MARGIN
                and sc_best >= MIN_ABS and sc_claim < MIN_CLAIM_ABS
                and sc_best >= RATIO_MIN * sc_claim):
            fixes.append((h["cn"], claimed, best_id))
            findings.append({
                "type": "gap_ref", "level": "fix",
                "detail": "假设%s 标注「对应缺口%d」，但内容更匹配「缺口%d」（关键词重合 %.3f vs %.3f；次选缺口%d %.3f），已自动纠正编号"
                          % (h["cn"], claimed, best_id, sc_claim, sc_best, second_gap, second)})
    return (_apply_fixes(best_text, fixes), findings)


def _apply_fixes(text, fixes):
    if not fixes:
        return text
    fix_map = {cn: (claimed, best) for cn, claimed, best in fixes}
    lines = text.splitlines(keepends=True)
    heads = []
    for i, ln in enumerate(lines):
        m = _HYP_HEAD.match(ln)
        if m:
            heads.append((i, m.group(1)))
    out = []
    for j, (i, cn) in enumerate(heads):
        end = heads[j + 1][0] if j + 1 < len(heads) else len(lines)
        block = "".join(lines[i:end])
        if cn in fix_map:
            claimed, best = fix_map[cn]
            block = re.sub(r"对应缺口%d(?!\d)" % claimed, "对应缺口%d" % best, block)
            block = re.sub(r"缺口%d(?!\d)" % claimed, "缺口%d" % best, block)
        out.append(block)
    prefix = "".join(lines[:heads[0][0]]) if heads else ""
    text2 = prefix + "".join(out)
    for cn, claimed, best in fixes:
        text2 = re.sub(r"假设%s\s*针对\s*缺口%d(?!\d)" % (cn, claimed),
                       "假设%s针对缺口%d" % (cn, best), text2)
    return text2


# ---------- 文献术语一致性 ----------
_BAND_WIDE = re.compile(r"宽禁带|宽带隙|ultra[\s\-‐‑_]*wide[\s\-‐‑_]*bandgap|wide[\s\-‐‑_]*bandgap", re.I)
_BAND_NARROW = re.compile(r"窄禁带|窄带隙|narrow[\s\-‐‑_]*bandgap", re.I)
_TITLE_RE = re.compile(r"《([^》]{6,})》")


def check_terminology(text):
    findings = []
    occ = {}
    for m in _TITLE_RE.finditer(text):
        title = m.group(1)
        fp = re.sub(r"[\s\-‐‑_（）()《》,.]+", "", title.lower())[:24]
        occ.setdefault(fp, []).append((title, m.start()))
    for fp, items in occ.items():
        if len(items) < 2:
            continue
        wide = narrow = False
        for title, start in items:
            ctx = text[max(0, start - 60): start + len(title) + 60]
            if _BAND_WIDE.search(ctx):
                wide = True
            if _BAND_NARROW.search(ctx):
                narrow = True
        if wide and narrow:
            findings.append({
                "type": "terminology", "level": "warn",
                "detail": "论文《%s》在不同段落被描述为「宽禁带/宽带隙」与「窄禁带/窄带隙」，术语自相矛盾，请人工核对"
                          % items[0][0]})
    return findings


def run_checks(knowledge_text, gaps_text, best_text, verify_text=""):
    """出报告前统一调用：返回 (修正后的 best_text, findings)。"""
    best_fixed, findings = check_gap_refs(best_text, gaps_text)
    combined = "\n".join(filter(None, [knowledge_text, gaps_text, best_fixed, verify_text]))
    findings += check_terminology(combined)
    return best_fixed, findings


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    print("consistency_check 模块 OK")
