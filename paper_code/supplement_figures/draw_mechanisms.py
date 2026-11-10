"""Implementation schematics; illustrative map topology, never a recorded trace."""

from draw_figure1 import bezier
from plot_style import (
    arrow, canvas, circle, line, marker, panel, rect, route, save_figure, text,
)


def evidence_tree(ax, center, rebuilt=False):
    root_y, concept_y, source_y = 64, 99, 139
    concepts = [center - 49, center, center + 49]
    for xx in concepts:
        bezier(ax, [(center, root_y + 4), (center, 80), (xx, 80), (xx, concept_y - 5)],
               "light", width=1.0)
    circle(ax, center, root_y, 4, face="blue", edge="blue")
    for j, xx in enumerate(concepts):
        gap = j == 1 and not rebuilt
        circle(ax, xx, concept_y, 5, face="white" if gap else "teal",
               edge="coral" if gap else "teal", lw=1.2)
    for xx, parent in [(center-62, center-49), (center-36, center-49), (center+49, center+49)]:
        line(ax, [(parent, concept_y+5), (xx, source_y-4)], "light", 0.95)
        rect(ax, xx-3.5, source_y-3.5, 7, 7, face="wash", edge="muted", lw=0.85)
    if rebuilt:
        for xx in [center-15, center, center+15]:
            line(ax, [(center, concept_y+5), (xx, source_y-4)], "teal", 1.0)
            rect(ax, xx-3.5, source_y-3.5, 7, 7, face="teal", edge="teal", lw=0.85)
    else:
        text(ax, center, 119, "Gap", size=8.5, ha="center", color="coral")


def figure2():
    height = 595
    fig, ax = canvas(height)
    panel(ax, "a", "Evidence-map updates", 12, 18)
    text(ax, 498, 18, "Implementation schematic", size=8.3, ha="right", color="muted")
    text(ax, 82, 44, "Map v", size=9.5, weight="bold", ha="center")
    text(ax, 434, 44, "Map v + 1", size=9.5, weight="bold", ha="center")
    evidence_tree(ax, 82)
    evidence_tree(ax, 434, rebuilt=True)
    text(ax, 257, 74, "Qualifying rebuild", size=9.3, weight="bold", ha="center")
    arrow(ax, (177, 95), (337, 95), color="teal", lw=1.8, scale=10)
    text(ax, 257, 116, "\u22653 new relevant sources", size=8.7, ha="center")
    text(ax, 257, 134, "\u226550% of the source pool", size=8.7, ha="center")
    rect(ax, 14, 160, 7, 7, face="wash", edge="muted", lw=0.8)
    text(ax, 29, 164, "Existing source", size=8.3, color="muted")
    rect(ax, 137, 160, 7, 7, face="teal", edge="teal", lw=0.8)
    text(ax, 152, 164, "New source", size=8.3, color="muted")
    text(ax, 498, 164, "Routine updates retain v", size=8.5, ha="right", color="muted")
    line(ax, [(12, 184), (498, 184)], "rule", 0.75)

    panel(ax, "b", "Persistent issue states", 12, 205)
    text(ax, 498, 205, "Stable IDs / full histories", size=8.3, ha="right", color="muted")
    route(ax, [(82, 265), (82, 247), (436, 247), (436, 265)], color="light", lw=1)
    text(ax, 259, 235, "Eligible active issues may archive directly", size=8.3, ha="center", color="muted")
    for xx, label, shape, color, fill in [
        (82, "active", "o", "coral", False),
        (257, "resolved", "D", "teal", True),
        (436, "archived", "s", "muted", False),
    ]:
        marker(ax, xx, 286, shape, color, size=11, fill=fill)
        text(ax, xx, 308, label, size=10.4, weight="bold", ha="center")
    arrow(ax, (99, 286), (238, 286), color="muted", lw=1.2, scale=8.5)
    text(ax, 168, 274, "reviewer state", size=8.5, ha="center", color="muted")
    arrow(ax, (277, 286), (417, 286), color="muted", lw=1.2, scale=8.5)
    text(ax, 347, 274, "archive eligible", size=8.5, ha="center", color="muted")
    bezier(ax, [(257, 319), (257, 344), (117, 344), (117, 304)], "coral", width=1.15).set_linestyle((0, (3, 2)))
    arrow(ax, (117, 304), (96, 288), color="coral", lw=1.15, scale=8, dash=(0, (3, 2)))
    text(ax, 188, 323, "new score <80", size=8.3, ha="center")
    bezier(ax, [(436, 319), (436, 393), (32, 393), (32, 304)], "coral", width=1.15).set_linestyle((0, (3, 2)))
    arrow(ax, (32, 304), (69, 288), color="coral", lw=1.15, scale=8, dash=(0, (3, 2)))
    text(ax, 254, 350, "Negative evidence / health-check score <88", size=8.3, ha="center")
    line(ax, [(12, 383), (498, 383)], "rule", 0.75)

    panel(ax, "c", "Nominal release checks", 12, 403)
    text(ax, 498, 403, "Override cases: Fig. 4", size=8.3, ha="right", color="muted")
    text(ax, 12, 431, "Shared requirements", size=9.4, weight="bold")
    for yy, label in [(454, "No anchor block"), (473, "Hypothesis \u2265 target"),
                      (492, "Dimension + novelty floors")]:
        line(ax, [(12, yy-6), (12, yy+6)], "blue", 1.7)
        text(ax, 21, yy, label, size=8.8)
    line(ax, [(170, 450), (179, 450), (179, 499), (170, 499)], "light", 0.85)
    arrow(ax, (183, 473), (236, 473), color="blue", lw=1.1, scale=8)
    text(ax, 256, 431, "Evidence", size=9.2, weight="bold", ha="center")
    line(ax, [(239, 455), (239, 491)], "blue", 1.05)
    arrow(ax, (239, 455), (326, 455), color="blue", lw=1.05, scale=8)
    text(ax, 282, 445, "\u226560", size=8.5, ha="center")
    marker(ax, 339, 455, "o", "blue", size=7, fill=True)
    text(ax, 353, 455, "validated", size=10, weight="bold")
    arrow(ax, (239, 491), (326, 491), color="teal", lw=1.05, scale=8)
    text(ax, 282, 481, "<60", size=8.5, ha="center")
    marker(ax, 339, 491, "D", "teal", size=7)
    text(ax, 353, 489, "exploratory", size=10, weight="bold")
    text(ax, 353, 505, "with a qualifying flag", size=8.3, color="muted")
    text(ax, 21, 536, "Otherwise", size=8.8, color="muted")
    arrow(ax, (89, 536), (326, 536), color="muted", lw=0.9, scale=8)
    marker(ax, 339, 536, "s", "muted", size=7)
    text(ax, 353, 536, "in_progress", size=10, weight="bold")
    rect(ax, 12, 562, 486, 25, face="wash", edge="wash", lw=0)
    text(ax, 23, 574.5, "Defaults", size=8.5, weight="bold")
    text(ax, 98, 574.5, "10 review rounds", size=8.5)
    text(ax, 226, 574.5, "Search threshold 4", size=8.5)
    text(ax, 366, 574.5, "Stagnation patience 3", size=8.5)
    return save_figure(fig, "figure2_core_mechanisms", height)
