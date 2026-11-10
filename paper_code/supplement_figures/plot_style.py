"""Shared publication primitives; accepted Figure 1 style retained in v3."""

from pathlib import Path
import json
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyArrowPatch, Polygon, Rectangle


ROOT = Path(__file__).resolve().parent
WIDTH = 180 / 25.4 * 72
PALETTE = {
    "ink": "#202B33",
    "muted": "#57636D",
    "light": "#A4ADB3",
    "rule": "#DCE1E4",
    "wash": "#F3F5F6",
    "blue": "#3C5488",
    "teal": "#00A087",
    "coral": "#E64B35",
    "cyan": "#4DBBD5",
    "blue_tint": "#EEF1F7",
    "teal_tint": "#E8F5F1",
    "coral_tint": "#FCEDE9",
    "dark_teal": "#006D5B",
}


def configure():
    font_files = [Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/arialbd.ttf")]
    for font_file in font_files:
        if font_file.exists():
            font_manager.fontManager.addfont(str(font_file))
    family = "Arial" if font_files[0].exists() else "DejaVu Sans"
    plt.rcParams.update({
        "font.family": family,
        "font.size": 8.5,
        "text.color": PALETTE["ink"],
        "axes.labelcolor": PALETTE["ink"],
        "xtick.color": PALETTE["muted"],
        "ytick.color": PALETTE["muted"],
        "axes.edgecolor": PALETTE["light"],
        "axes.linewidth": 0.6,
        "xtick.major.width": 0.6,
        "ytick.major.width": 0.6,
        "xtick.major.size": 3,
        "ytick.major.size": 3,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "svg.fonttype": "none",
        "svg.hashsalt": "paper-figures-v2-20261013",
        "savefig.facecolor": "white",
        "figure.facecolor": "white",
        "hatch.linewidth": 0.5,
    })
    return family


def canvas(height):
    fig = plt.figure(figsize=(WIDTH / 72, height / 72))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, WIDTH)
    ax.set_ylim(height, 0)
    ax.set_axis_off()
    return fig, ax


def text(ax, x, y, content, size=8.5, color="ink", weight="normal", ha="left", va="center", **kwargs):
    return ax.text(x, y, content, fontsize=size, color=PALETTE.get(color, color),
                   fontweight=weight, ha=ha, va=va, linespacing=1.35, **kwargs)


def panel(ax, letter, label, x, y):
    text(ax, x, y, letter, size=11, weight="bold")
    text(ax, x + 17, y, label, size=10.2, weight="bold")


def line(ax, points, color="rule", lw=0.8, dash=None, zorder=1):
    item = Line2D([p[0] for p in points], [p[1] for p in points],
                  color=PALETTE.get(color, color), linewidth=lw, zorder=zorder,
                  solid_capstyle="round", solid_joinstyle="round")
    if dash is not None:
        item.set_linestyle(dash)
    ax.add_line(item)
    return item


def arrow(ax, start, end, color="muted", lw=1.0, style="-|>", curve=0, dash="-", scale=8, zorder=2):
    item = FancyArrowPatch(start, end, arrowstyle=style, mutation_scale=scale,
                           connectionstyle=f"arc3,rad={curve}", linewidth=lw,
                           linestyle=dash, color=PALETTE.get(color, color),
                           shrinkA=0, shrinkB=0, zorder=zorder)
    ax.add_patch(item)
    return item


def route(ax, points, color="muted", lw=1.0, dash=None, scale=8):
    line(ax, points[:-1], color=color, lw=lw, dash=dash)
    arrow(ax, points[-2], points[-1], color=color, lw=lw,
          dash=dash or "-", scale=scale)


def rect(ax, x, y, w, h, face="white", edge="rule", lw=0.8, zorder=1):
    item = Rectangle((x, y), w, h, facecolor=PALETTE.get(face, face),
                     edgecolor=PALETTE.get(edge, edge), linewidth=lw, zorder=zorder)
    ax.add_patch(item)
    return item


def circle(ax, x, y, radius, face="white", edge="muted", lw=0.8, zorder=2):
    item = Circle((x, y), radius, facecolor=PALETTE.get(face, face),
                  edgecolor=PALETTE.get(edge, edge), linewidth=lw, zorder=zorder)
    ax.add_patch(item)
    return item


def marker(ax, x, y, kind, color="blue", size=5.5, fill=False, zorder=3):
    color_value = PALETTE.get(color, color)
    ax.plot(x, y, marker=kind, markersize=size, linestyle="none",
            markerfacecolor=color_value if fill else "white",
            markeredgecolor=color_value, markeredgewidth=1.05, zorder=zorder)


def document(ax, x, y, w=38, h=48, accent="blue", rows=4):
    fold = 8
    outline = Polygon([(x, y), (x+w-fold, y), (x+w, y+fold),
                       (x+w, y+h), (x, y+h)], closed=True,
                      facecolor="white", edgecolor=PALETTE[accent], linewidth=1.1)
    ax.add_patch(outline)
    line(ax, [(x+w-fold, y), (x+w-fold, y+fold), (x+w, y+fold)], accent, 0.8)
    line(ax, [(x+7, y+15), (x+w-9, y+15)], accent, 1.8)
    for i in range(rows):
        yy = y + 24 + i * 6
        if yy < y + h - 4:
            line(ax, [(x+7, yy), (x+w-7-(i % 2)*6, yy)], "light", 0.75)


def axes_at(fig, height, x, y, w, h):
    return fig.add_axes([x / WIDTH, (height-y-h) / height, w / WIDTH, h / height])


def save_figure(fig, name, height):
    pdf_dir = ROOT / "output" / "pdf"
    svg_dir = ROOT / "output" / "svg"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    svg_dir.mkdir(parents=True, exist_ok=True)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    figure_bbox = fig.bbox
    failures = []
    sizes = []
    text_count = 0
    bounds = []
    for ax in fig.axes:
        artists = list(ax.texts)
        if ax.axison:
            artists += list(ax.get_xticklabels()) + list(ax.get_yticklabels())
            artists += [ax.xaxis.label, ax.yaxis.label]
        for item in artists:
            if not item.get_visible() or not item.get_text():
                continue
            text_count += 1
            sizes.append(item.get_fontsize())
            bbox = item.get_window_extent(renderer)
            bounds.append((item.get_text(), bbox))
            if (bbox.x0 < figure_bbox.x0 - 0.5 or bbox.y0 < figure_bbox.y0 - 0.5 or
                    bbox.x1 > figure_bbox.x1 + 0.5 or bbox.y1 > figure_bbox.y1 + 0.5):
                failures.append({"text": item.get_text(), "bbox_px": [round(v, 2) for v in bbox.bounds]})
    overlaps = []
    for i, (label, bbox) in enumerate(bounds):
        for other, other_bbox in bounds[i+1:]:
            overlap_x = min(bbox.x1, other_bbox.x1) - max(bbox.x0, other_bbox.x0)
            overlap_y = min(bbox.y1, other_bbox.y1) - max(bbox.y0, other_bbox.y0)
            if overlap_x > 0.8 and overlap_y > 0.8:
                overlaps.append([label, other])
    if sizes and min(sizes) < 8.2:
        failures.append({"font_below_8_2_pt": min(sizes)})
    report = {"figure": name, "width_mm": 180, "height_mm": round(height / 72 * 25.4, 2),
              "minimum_font_pt": min(sizes), "maximum_font_pt": max(sizes),
              "text_count": text_count, "out_of_canvas": failures, "text_overlaps": overlaps}
    fig.savefig(pdf_dir / f"{name}.pdf", metadata={"Creator": "Matplotlib; source included",
                "Title": name.replace("_", " "), "CreationDate": None, "ModDate": None})
    fig.savefig(svg_dir / f"{name}.svg", metadata={"Date": None, "Creator": "Matplotlib; source included"})
    plt.close(fig)
    return report


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
