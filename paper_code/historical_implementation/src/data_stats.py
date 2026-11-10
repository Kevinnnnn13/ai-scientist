# -*- coding: utf-8 -*-
"""data_stats.py：实验数据清洗与统计分析（命题「数据清洗与统计分析」环节）。

输入：CSV / TSV / JSON / XLSX（XLSX 需 openpyxl），或 pandas DataFrame。
输出：缺失值 / 重复行 / 异常值（IQR）、数值列 describe、两两 Pearson 相关、
正态性（Shapiro-Wilk）、可视化图表建议；可选输出 PNG 图表。

用法：
  python src/data_stats.py <文件路径> [--out 报告.md] [--charts]
"""
import argparse
import json
import os

import numpy as np
import pandas as pd
from scipy import stats


def load_table(path):
    """按扩展名读取表格文件，返回 DataFrame。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".csv":
        return pd.read_csv(path)
    if ext in (".tsv", ".txt"):
        return pd.read_csv(path, sep="\t")
    if ext == ".json":
        return pd.read_json(path)
    if ext in (".xlsx", ".xls"):
        return pd.read_excel(path)
    raise ValueError(f"不支持的文件类型：{ext}")


def _is_numeric(series):
    return pd.api.types.is_numeric_dtype(series)


def _describe(df, numeric_cols):
    """把 describe 转成 JSON 友好的 dict（NaN -> None，数值保留 4 位）。"""
    if not numeric_cols:
        return {}
    d = df[numeric_cols].describe().T
    out = {}
    for col in numeric_cols:
        row = d.loc[col]
        out[str(col)] = {
            str(k): (None if pd.isna(v) else round(float(v), 4))
            for k, v in row.items()
        }
    return out


def _outliers(df, numeric_cols):
    out = {}
    for col in numeric_cols:
        s = df[col].dropna()
        if len(s) < 4:
            continue
        q1, q3 = s.quantile(0.25), s.quantile(0.75)
        iqr = q3 - q1
        if iqr <= 0:
            continue
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        mask = (s < lo) | (s > hi)
        if int(mask.sum()):
            out[str(col)] = {
                "count": int(mask.sum()),
                "lower": round(float(lo), 4),
                "upper": round(float(hi), 4),
                "values": [round(float(x), 4) for x in s[mask].tolist()[:10]],
            }
    return out


def _correlations(df, numeric_cols):
    pairs = []
    for i in range(len(numeric_cols)):
        for j in range(i + 1, len(numeric_cols)):
            sub = pd.concat([df[numeric_cols[i]], df[numeric_cols[j]]], axis=1).dropna()
            if len(sub) < 3:
                continue
            r, p = stats.pearsonr(sub.iloc[:, 0], sub.iloc[:, 1])
            if not np.isnan(r) and abs(r) >= 0.5:
                pairs.append({
                    "a": str(numeric_cols[i]),
                    "b": str(numeric_cols[j]),
                    "r": round(float(r), 4),
                    "p": round(float(p), 4),
                })
    pairs.sort(key=lambda x: -abs(x["r"]))
    return pairs


def _normality(df, numeric_cols):
    out = {}
    for col in numeric_cols:
        s = df[col].dropna()
        if 3 <= len(s) <= 5000:
            try:
                w, p = stats.shapiro(s)
                out[str(col)] = {"w": round(float(w), 4), "p": round(float(p), 4)}
            except Exception:
                pass
    return out


def _suggest_charts(df, numeric_cols, correlations):
    out = []
    if len(numeric_cols) == 1:
        out.append({"columns": [str(numeric_cols[0])], "chart": "histogram/boxplot",
                    "reason": "单数值列，看分布形态与离群点"})
    if len(numeric_cols) >= 2:
        out.append({"columns": [str(c) for c in numeric_cols[:2]], "chart": "scatter",
                    "reason": "检查两变量是否存在关系"})
        if correlations:
            top = correlations[0]
            out.append({"columns": [top["a"], top["b"]], "chart": "scatter+trendline",
                        "reason": f"相关系数 r={top['r']}"})
    cat_cols = [c for c in df.columns
                if c not in numeric_cols and 2 <= df[c].nunique(dropna=True) <= 20]
    if cat_cols and numeric_cols:
        for c in cat_cols[:2]:
            out.append({"columns": [str(c), str(numeric_cols[0])], "chart": "box/bar",
                        "reason": "按类别分组比较"})
    return out


def analyze(df):
    """对 DataFrame 做清洗与统计，返回结构化 dict。"""
    df = df.copy()
    numeric_cols = [c for c in df.columns if _is_numeric(df[c])]
    n_rows, n_cols = df.shape

    missing = {}
    for c in df.columns:
        m = int(df[c].isna().sum())
        if m:
            missing[str(c)] = {"count": m, "ratio": round(m / max(n_rows, 1), 4)}

    correlations = _correlations(df, numeric_cols)
    return {
        "shape": [int(n_rows), int(n_cols)],
        "columns": [str(c) for c in df.columns],
        "numeric_columns": [str(c) for c in numeric_cols],
        "duplicated_rows": int(df.duplicated().sum()),
        "missing": missing,
        "describe": _describe(df, numeric_cols),
        "outliers": _outliers(df, numeric_cols),
        "correlations": correlations,
        "normality": _normality(df, numeric_cols),
        "chart_suggestions": _suggest_charts(df, numeric_cols, correlations),
    }


def analyze_file(path):
    """读取文件并分析，结果里带上文件路径。"""
    df = load_table(path)
    result = analyze(df)
    result["file"] = os.path.abspath(path)
    return result


def render_markdown(result):
    """把分析结果渲染成中文 Markdown 报告。"""
    rows, cols = result["shape"]
    lines = [
        "# 数据清洗与统计分析报告",
        "",
        f"- 数据规模：{rows} 行 × {cols} 列",
        f"- 数值列：{', '.join(result['numeric_columns']) or '（无）'}",
        f"- 重复行：{result['duplicated_rows']}",
    ]
    if result.get("file"):
        lines.append(f"- 来源：{result['file']}")

    if result["missing"]:
        lines += ["", "## 缺失值"]
        for c, m in result["missing"].items():
            lines.append(f"- `{c}`：{m['count']} 个（{m['ratio']:.1%}）")
    else:
        lines += ["", "## 缺失值", "- 无缺失"]

    if result["describe"]:
        lines += ["", "## 描述统计"]
        keys = ["count", "mean", "std", "min", "25%", "50%", "75%", "max"]
        header = "| 列 | " + " | ".join(keys) + " |"
        lines += [header, "|---" * (len(keys) + 1) + "|"]
        for c, d in result["describe"].items():
            cells = ["-" if d.get(k) is None else str(d.get(k)) for k in keys]
            lines.append(f"| `{c}` | " + " | ".join(cells) + " |")

    if result["outliers"]:
        lines += ["", "## 异常值（IQR 1.5 倍）"]
        for c, o in result["outliers"].items():
            vals = ", ".join(str(v) for v in o["values"])
            lines.append(f"- `{c}`：{o['count']} 个，区间外 [{o['lower']}, {o['upper']}]，示例值 {vals}")
    else:
        lines += ["", "## 异常值", "- 未检出"]

    if result["correlations"]:
        lines += ["", "## 两两相关（|r| ≥ 0.5）"]
        for pair in result["correlations"]:
            lines.append(f"- `{pair['a']}` ↔ `{pair['b']}`：r={pair['r']}，p={pair['p']}")

    if result["normality"]:
        lines += ["", "## 正态性（Shapiro-Wilk）"]
        for c, n in result["normality"].items():
            lines.append(f"- `{c}`：W={n['w']}，p={n['p']}")

    if result["chart_suggestions"]:
        lines += ["", "## 可视化图表建议"]
        for s in result["chart_suggestions"]:
            lines.append(f"- `{'`, `'.join(s['columns'])}` → {s['chart']}（{s['reason']}）")

    return "\n".join(lines) + "\n"


def _safe_label(name, idx):
    """图表标签兜底：非 ASCII 的列名换成 col_序号，避免中文字体豆腐块。"""
    try:
        name.encode("ascii")
        return str(name)
    except UnicodeEncodeError:
        return f"col_{idx}"


def make_charts(df, result, out_dir):
    """渲染基础 PNG 图表，返回保存路径列表（不阻塞主流程，失败跳过）。"""
    os.makedirs(out_dir, exist_ok=True)
    saved = []
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        return saved

    numeric_cols = [c for c in df.columns if _is_numeric(df[c])]
    for idx, c in enumerate(numeric_cols[:4]):
        try:
            plt.figure()
            plt.hist(df[c].dropna(), bins=20)
            plt.title("histogram")
            plt.xlabel(_safe_label(c, idx))
            p = os.path.join(out_dir, f"hist_{idx}.png")
            plt.tight_layout()
            plt.savefig(p, dpi=100)
            plt.close()
            saved.append(p)
        except Exception:
            plt.close("all")

    if result["correlations"]:
        top = result["correlations"][0]
        a, b = top["a"], top["b"]
        if a in df.columns and b in df.columns:
            try:
                plt.figure()
                plt.scatter(df[a], df[b], s=12, alpha=0.7)
                plt.title("top correlation")
                plt.xlabel(_safe_label(a, 0))
                plt.ylabel(_safe_label(b, 1))
                p = os.path.join(out_dir, "scatter_top.png")
                plt.tight_layout()
                plt.savefig(p, dpi=100)
                plt.close()
                saved.append(p)
            except Exception:
                plt.close("all")
    return saved


def main(argv=None):
    parser = argparse.ArgumentParser(description="数据清洗与统计分析")
    parser.add_argument("path", help="CSV / TSV / JSON / XLSX 文件路径")
    parser.add_argument("--out", help="Markdown 报告输出路径")
    parser.add_argument("--charts-dir", help="输出 PNG 图表的目录（缺省不画图）")
    args = parser.parse_args(argv)

    df = load_table(args.path)
    result = analyze(df)
    result["file"] = os.path.abspath(args.path)
    report = render_markdown(result)

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已写入：{args.out}")
    else:
        print(report)

    if args.charts_dir:
        paths = make_charts(df, result, args.charts_dir)
        print("已生成图表：" + ("、".join(paths) if paths else "（无）"))


if __name__ == "__main__":
    main()
