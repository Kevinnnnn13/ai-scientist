"""Evidence-linked architecture figure, illustrated with a recorded math01 state."""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys

import matplotlib.pyplot as plt
from matplotlib.path import Path as VectorPath
from matplotlib.patches import PathPatch
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader

from plot_style import (
    ROOT, WIDTH, PALETTE, arrow, canvas, circle, configure, line,
    marker, panel, rect, route, save_figure, text, write_json,
)


STEM = "figure1_evidence_workflow_v3"
HEIGHT = 546
STATE_SHA256 = "948352F730C4F089051C87649D7358E8606FEA4D6D95A6D28A1FBD571C5D26C1"
V2_SHA256 = "0E67F68D80F7E587C3C386BEE33AC726240EF6A89DB34220C6A591743A631116"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def seed_snapshot(state_path, v2_snapshot):
    assert digest(state_path) == STATE_SHA256, "The source state differs from the frozen audit input."
    assert digest(v2_snapshot) == V2_SHA256, "The v2 data snapshot has changed."
    state = json.loads(state_path.read_text(encoding="utf-8"))
    v2 = json.loads(v2_snapshot.read_text(encoding="utf-8"))
    raw_tree = state["knowledge_tree"]
    sources, links, concepts = [], [], []
    by_identity = {}
    for node in raw_tree["sub_problems"]:
        concepts.append({"id": node["id"], "name": node["name"],
                         "coverage": node["coverage"], "open_debate": node["open_debate"],
                         "source_assignments": len(node["papers"])})
        for paper in node["papers"]:
            title = paper.get("\u6807\u9898") or paper.get("title") or ""
            doi = str(paper.get("DOI") or paper.get("doi") or "").strip().lower()
            doi = doi.removeprefix("https://doi.org/").removeprefix("http://doi.org/")
            identity = doi or paper.get("\u94fe\u63a5") or paper.get("url") or title
            assert identity, paper
            if identity not in by_identity:
                source_id = "S" + str(len(sources)+1)
                by_identity[identity] = source_id
                sources.append({"id": source_id, "identity": identity,
                                "title_as_recorded": title, "record": paper})
            links.append({"source_id": by_identity[identity], "concept_id": node["id"]})
    result = {
        "run_id": v2["case"]["run_id"], "question": raw_tree["root_question"],
        "tree_version": state["tree_version"], "sources": sources, "concepts": concepts,
        "links": links, "issues": v2["case"]["issues"], "rounds": v2["case"]["rounds"],
        "terminal": {name: state[name] for name in ["hypothesis_score", "data_score", "plan_status",
                      "total_soft_searches", "search_exhausted", "best_score", "best_data_score"]},
        "provenance": {"state_path": str(state_path), "state_sha256": STATE_SHA256,
                       "v2_snapshot_path": str(v2_snapshot), "v2_snapshot_sha256": V2_SHA256},
        "semantics": {
            "source_links": "Recorded paper-to-concept assignments; not verified scientific support.",
            "source_ids": "Deterministic display IDs, deduplicated by DOI, URL or recorded title.",
            "routes": "Schematic implementation routes, not reconstructed causal events.",
            "proposal": "Paraphrased untested G/C comparison, also used in the frozen Figure 3 caption.",
        },
    }
    target = ROOT / "data/figure1_snapshot.json"
    write_json(target, result)


def bezier(ax, vertices, color, width=1, alpha=1, zorder=1):
    path = VectorPath(vertices, [VectorPath.MOVETO]+[VectorPath.CURVE4]*(len(vertices)-1))
    patch = PathPatch(path, edgecolor=PALETTE.get(color, color), facecolor="none",
                      linewidth=width, alpha=alpha, zorder=zorder,
                      capstyle="round", joinstyle="round")
    ax.add_patch(patch)
    return patch


def draw(data):
    configure()
    fig, ax = canvas(HEIGHT)
    panel(ax, "a", "Evidence-linked research planning", 12, 18)
    text(ax, 498, 18, "Original F0 / math01 example", size=8.3, ha="right", color="muted")
    rect(ax, 12, 37, 486, 36, face="wash", edge="wash", lw=0)
    line(ax, [(12, 37), (12, 73)], "teal", 2.2)
    text(ax, 23, 47, "RESEARCH QUESTION", size=8.2, weight="bold", color="muted")
    text(ax, 23, 62, "Can prime-gap models yield distinguishable predictions?", size=9.5)

    text(ax, 14, 94, "Source records", size=9, weight="bold")
    text(ax, 154, 94, "Research concepts", size=9, weight="bold")
    text(ax, 270, 94, "Links", size=8.2, ha="center", color="muted")
    source_y = {source["id"]: 115+i*174/max(1, len(data["sources"])-1)
                for i, source in enumerate(data["sources"])}
    concept_y = {node["id"]: 116+i*28 for i, node in enumerate(data["concepts"])}
    rect(ax, 130, 130, 152, 29, face="coral_tint", edge="coral_tint", lw=0, zorder=0)
    for edge in data["links"]:
        start_y, end_y = source_y[edge["source_id"]], concept_y[edge["concept_id"]]
        bezier(ax, [(40, start_y), (83, start_y), (96, end_y), (136, end_y)],
               color="#78BAAF", width=0.78, alpha=0.64)
    for source_id, yy in source_y.items():
        circle(ax, 37, yy, 2.55, face="blue", edge="white", lw=0.45, zorder=3)
    labels = {
        1: "Prime-gap statistics", 2: "Hardy-Littlewood\nprime tuples",
        3: "Probabilistic models", 4: "Testability", 5: "Gap correlations",
        6: "Extreme gaps", 7: "Riemann hypothesis",
    }
    for node in data["concepts"]:
        yy = concept_y[node["id"]]
        gap = node["coverage"] == "gap"
        circle(ax, 140, yy, 4.1 if not gap else 5.1,
               face="white" if gap else "teal", edge="coral" if gap else "teal", lw=1.1)
        text(ax, 153, yy, labels[node["id"]], size=8.5,
             weight="bold" if gap else "normal")
        text(ax, 270, yy, str(node["source_assignments"]), ha="center", size=8.5,
             weight="bold" if gap else "normal")
    text(ax, 14, 309, f'{len(data["sources"])} unique records / 7 concepts', size=8.3, color="muted")
    marker(ax, 18, 329, "o", "teal", size=5, fill=True)
    text(ax, 28, 329, "Mapped", size=8.2, color="muted")
    marker(ax, 111, 329, "o", "coral", size=5)
    text(ax, 122, 329, "No source mapped", size=8.2, color="muted")

    # The structured proposal is the generated object, distinct from its source map.
    rect(ax, 316, 103, 173, 129, face="blue_tint", edge="#C4CCDC", lw=0.65)
    rect(ax, 316, 103, 173, 24, face="blue", edge="blue", lw=0)
    text(ax, 328, 115, "Candidate hypothesis", size=9.5, color="white", weight="bold")
    text(ax, 328, 143, "Granville-type vs", size=10.4, weight="bold")
    text(ax, 328, 158, "Cramer-type models", size=10.4, weight="bold")
    for yy, label in [(181, "Gap autocorrelation"), (199, "Tuple density"), (217, "Short-interval variance")]:
        rect(ax, 329, yy-2, 3, 4, face="blue", edge="blue", lw=0)
        text(ax, 340, yy, label, size=8.5)
    arrow(ax, (285, 115), (311, 115), color="blue", lw=1.15, scale=8)
    text(ax, 298, 104, "inform", size=8.2, ha="center", color="muted")
    arrow(ax, (402, 234), (402, 251), color="muted", lw=1.05, scale=8)

    # The two examples are real issue IDs; the ledger contains ten issues in total.
    rect(ax, 316, 257, 173, 83, face="white", edge="#E2B8AD", lw=0.8)
    rect(ax, 316, 257, 173, 24, face="coral_tint", edge="coral_tint", lw=0)
    line(ax, [(316, 257), (489, 257)], "coral", 2)
    text(ax, 328, 270, "Review & route", size=9.5, weight="bold")
    for yy, issue_id, label in [(299, "I1", "Parameter support"), (324, "I2", "Tree/source mismatch")]:
        text(ax, 328, yy, issue_id, size=8.5, weight="bold", color="blue")
        text(ax, 348, yy, label, size=8.5)
    route(ax, [(283, 144), (297, 144), (297, 324), (311, 324)], color="coral", lw=0.9)
    route(ax, [(490, 273), (505, 273), (505, 176), (490, 176)],
          color="coral", lw=1, dash=(0, (3, 2)))
    text(ax, 497, 224, "revise", size=8.2, rotation=90, ha="center")
    bezier(ax, [(402, 342), (402, 372), (379, 383), (322, 383),
                (103, 383), (7, 370), (7, 342)], "coral", width=1.5)
    line(ax, [(7, 342), (7, 289)], "coral", 1.5)
    arrow(ax, (7, 289), (30, 289), color="coral", lw=1.5, scale=9)
    text(ax, 210, 371, "Retrieval routing", size=9, ha="center", weight="bold")

    rect(ax, 12, 399, 486, 24, face="wash", edge="wash", lw=0)
    text(ax, 24, 411, "Saved state", size=8.6, weight="bold")
    text(ax, 113, 411, "Map version / issue histories / scores / budgets", size=8.5, color="muted")
    panel(ax, "b", "State-aware export", 12, 445)
    text(ax, 498, 445, "Recorded terminal state", size=8.3, color="muted", ha="right")
    text(ax, 16, 468, "Review round 7", size=8.4, weight="bold", color="muted")
    text(ax, 16, 489, "Hypothesis 70 / evidence 84", size=9)
    text(ax, 16, 509, "9 active / 1 resolved", size=9)
    text(ax, 16, 529, "4 counted / exhausted", size=9)
    arrow(ax, (206, 504), (295, 504), color="blue", lw=1.1, scale=8)
    text(ax, 250, 491, "export", size=8.3, ha="center", color="muted")
    rect(ax, 314, 468, 180, 67, face="wash", edge="rule", lw=0.8)
    rect(ax, 308, 462, 180, 67, face="white", edge="blue", lw=0.85)
    text(ax, 320, 479, "Hypothesis + audit trail", size=9.5, weight="bold")
    line(ax, [(320, 491), (476, 491)], "rule", 0.8)
    marker(ax, 324, 508, "s", "muted", size=6)
    text(ax, 338, 508, "in_progress", size=10, weight="bold")
    return save_figure(fig, STEM, HEIGHT)


def get_poppler(explicit):
    if explicit:
        return explicit
    located = shutil.which("pdftoppm")
    if located:
        return located
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("Set --pdftoppm to an installed Poppler pdftoppm executable.")


def compare(previous_png, current_png):
    images = []
    for source in [previous_png, current_png]:
        image = Image.open(source).convert("RGB")
        images.append(image.resize((1050, round(image.height*1050/image.width)), Image.Resampling.LANCZOS))
    height = max(image.height for image in images)+102
    sheet = Image.new("RGB", (2154, height), "#E8ECEF")
    draw = ImageDraw.Draw(sheet)
    font_path = Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 27) if font_path.exists() else ImageFont.load_default()
    for i, image in enumerate(images):
        x = 18+i*1077
        draw.rectangle((x, 18, x+1059, height-18), fill="white")
        draw.text((x+14, 28), ["Previous / v2", "New / v3"][i], font=font, fill=PALETTE["ink"])
        sheet.paste(image, (x+5, 75))
    sheet.save(ROOT / "comparison_v2_v3.png")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed-state", type=Path)
    parser.add_argument("--v2-data", type=Path)
    parser.add_argument("--previous-png", type=Path)
    parser.add_argument("--pdftoppm")
    args = parser.parse_args()
    if args.seed_state:
        assert args.v2_data
        seed_snapshot(args.seed_state, args.v2_data)
    snapshot = ROOT / "data/figure1_snapshot.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    assert len(data["concepts"]) == 7 and len(data["links"]) == 28
    assert [n["source_assignments"] for n in data["concepts"]] == [10, 0, 3, 2, 3, 6, 4]
    assert [n["id"] for n in data["concepts"] if n["coverage"] == "gap"] == [2]
    assert data["terminal"]["plan_status"] == "in_progress"
    assert data["terminal"]["hypothesis_score"] == 70 and data["terminal"]["data_score"] == 84
    assert data["terminal"]["total_soft_searches"] == 4 and data["terminal"]["search_exhausted"]
    assert Counter(issue["statuses"][-1] for issue in data["issues"]) == {"active": 9, "resolved": 1}
    layout = draw(data)
    pdf = ROOT / "output/pdf" / f"{STEM}.pdf"
    subprocess.run([get_poppler(args.pdftoppm), "-singlefile", "-r", "300", "-png", str(pdf), str(pdf.with_suffix(""))],
                   capture_output=True, check=True)
    png = pdf.with_suffix(".png")
    image = Image.open(png).convert("RGB")
    image = image.resize((1250, round(image.height*1250/image.width)), Image.Resampling.LANCZOS)
    image.save(ROOT / "preview.png")
    ImageOps.grayscale(image).save(ROOT / "grayscale.png")
    page_width_preview = image.resize((850, round(image.height*850/image.width)), Image.Resampling.LANCZOS)
    page_width_preview.save(ROOT / "publication_width_preview.png")
    if args.previous_png:
        compare(args.previous_png, png)
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert abs(float(page.mediabox.width)-WIDTH) < 0.01
    font_report = []
    for ref in page["/Resources"]["/Font"].values():
        font = ref.get_object()
        for descendant in font.get("/DescendantFonts", [font]):
            actual = descendant.get_object()
            descriptor = actual.get("/FontDescriptor")
            embedded = descriptor and any(k in descriptor.get_object() for k in ["/FontFile", "/FontFile2", "/FontFile3"])
            font_report.append({"font": str(actual["/BaseFont"]), "embedded": bool(embedded)})
    assert all(f["embedded"] for f in font_report)
    for obj in page["/Resources"].get("/XObject", {}).values():
        assert obj.get_object().get("/Subtype") != "/Image"
    write_json(ROOT / "verification_report.json", {
        "layout": layout, "fonts": font_report, "pure_vector_pdf": True,
        "source_count": len(data["sources"]), "concept_count": 7, "assignment_count": 28,
        "snapshot_sha256": digest(snapshot), "pdf_sha256": digest(pdf),
        "source_assignments_not_independent_evidence_validation": True,
        "new_experiments_or_statistical_tests": False,
    })
    versions = {name: importlib.metadata.version(name) for name in ["matplotlib", "Pillow", "numpy", "pypdf"]}
    write_json(ROOT / "runtime_versions.json", {"python": platform.python_version(), "packages": versions})
    (ROOT / "requirements.txt").write_text("\n".join(f"{n}=={v}" for n, v in versions.items())+"\n", encoding="ascii")
    print(json.dumps({"layout": layout, "sources": len(data["sources"]), "links": 28,
                      "pdf_sha256": digest(pdf)}, indent=2))
    if layout["out_of_canvas"] or layout["text_overlaps"]:
        raise SystemExit("Layout issue found; inspect the retained render before packaging.")


if __name__ == "__main__":
    main()
