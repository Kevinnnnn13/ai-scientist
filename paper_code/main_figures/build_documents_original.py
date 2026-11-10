"""Build revised article, supplement and figures from verified saved records."""

import copy
import hashlib
import json
from pathlib import Path
import re
import sys
from zipfile import ZipFile
from PIL import Image

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RUNS = ROOT / "robustness_runs"
ORIGINAL = Path("C:/Users/22011/Documents/xwechat_files/wxid_n3f82002hbvj12_18fa/msg/file/2026-10/manuscript_advisor_checked.docx")
FIGURES = HERE / "figures"


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


formal = read(RUNS / "programmatic_release_v21_formal_figures_20261015/summary.json")
supp = read(RUNS / "release_supplement_cd_20261015/summary.json")
fair = read(RUNS / "release_fairness_20261015/fairness.json")
audit = read(RUNS / "programmatic_release_v21_formal_audit_20261015/audit.json")
assert supp["completed"] == 96 and supp["execution_failures"] == 0
assert supp["groups"]["C"]["eligible_release"] == supp["groups"]["D"]["eligible_release"] == 9
assert supp["C_receipt_diagnostic"]["changed_decisions"] == 0
assert fair["summary"]["locator_counterfactual"]["workflow"]["edited_released"] == 15
source_extract = read(ROOT / "docs/submission_prep_20261015/source_extracts/manuscript.json")
assert hashlib.sha256(ORIGINAL.read_bytes()).hexdigest() == source_extract["source_sha256"]


def save_figure(fig, name):
    fig.savefig(FIGURES / (name + ".png"), dpi=240, bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURES / (name + ".pdf"), bbox_inches="tight", facecolor="white")
    fig.savefig(FIGURES / (name + ".svg"), bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figures():
    global plt, np, Rectangle, FancyArrowPatch
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Rectangle, FancyArrowPatch
    FIGURES.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 10,
        "pdf.fonttype": 42, "svg.fonttype": "none",
    })
    values = []
    for i in range(8):
        values.append([sum(r["released"] for r in audit["rows"]
                           if r["kind"] == "component" and r["condition"] == f"T{i}"
                           and r["controller"] == arm) for arm in "ABC"])
    values = np.array(values)
    fig, axes = plt.subplots(1, 2, figsize=(10.2, 6.7), gridspec_kw={"width_ratios": [3, 2]})
    labels = [
        "T0  Supported result", "T1  Supported locator", "T2  Missing evidence",
        "T3  Conflicting evidence", "T4  Fabricated own work",
        "T5  Missing + override", "T6  Conflict + override", "T7  Untrusted instruction",
    ]
    for axis, data, cols, title in (
        (axes[0], values, list("ABC"), "a  Original formal comparison"),
        (axes[1], np.array([[supp["groups"][a]["by_condition"][f"T{i}"]["released"]
                            for a in ("C", "D")] for i in range(8)]),
         ["C", "D"], "b  Post hoc matched-call comparison"),
    ):
        for i in range(8):
            for j in range(len(cols)):
                correct = data[i, j] / 6 if i < 2 else 1 - data[i, j] / 6
                good, bad = np.array([0.74, 0.89, 0.85]), np.array([0.97, 0.80, 0.79])
                color = tuple(good * correct + bad * (1 - correct))
                axis.add_patch(Rectangle((j - .5, i - .5), 1, 1, facecolor=color,
                                         edgecolor="white", linewidth=2))
                axis.text(j, i, f"{data[i,j]}/6", ha="center", va="center", fontsize=12)
        axis.set(xlim=(-.5, len(cols) - .5), ylim=(7.5, -.5),
                 xticks=range(len(cols)), xticklabels=cols, yticks=range(8))
        axis.set_yticklabels(labels if axis is axes[0] else [""] * 8)
        axis.xaxis.tick_top()
        axis.tick_params(length=0, pad=8)
        axis.set_title(title, loc="left", fontsize=11, pad=37)
        axis.axhline(1.5, color="black", linewidth=1)
        for spine in axis.spines.values():
            spine.set_visible(False)
    fig.subplots_adjust(left=.25, right=.97, top=.83, bottom=.18, wspace=.28)
    fig.text(.03, .105, "Each cell: released / six inputs. T0-T1 should release; T2-T7 should withhold.", fontsize=10)
    fig.text(.03, .065, "Green: more correct actions. Red: more incorrect actions. Original and post hoc calls remain separate.", fontsize=9)
    fig.text(.03, .025, "Offline A-English: T4 releases 0/6; total false releases 30/36 (original A: 36/36).", fontsize=10)
    save_figure(fig, "fig1")

    fig, axis = plt.subplots(figsize=(10.2, 5.9))
    axis.set(xlim=(0, 10.2), ylim=(0, 5.9))
    axis.axis("off")
    def box(x, y, width, height, text, color):
        axis.add_patch(Rectangle((x, y), width, height, facecolor=color, edgecolor="#999999", lw=.8))
        axis.text(x + width/2, y + height/2, text, ha="center", va="center", fontsize=10, linespacing=1.5)
    def arrow(a, b, dashed=False):
        axis.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12,
                                      color="#505050", lw=1, linestyle="--" if dashed else "-"))
    axis.text(0, 5.65, "Original formal clean generation", weight="bold", fontsize=13)
    box(.05, 4.0, 2.4, 1.05, "A: 18 final answers\nAll independently eligible", "#EEEEEE")
    box(3.15, 4.0, 3.4, 1.05, "All retain legal Figure 2\nPattern screen blocks release", "#F7DFDB")
    box(7.3, 4.0, 2.7, 1.05, "Released 0/18\nWithheld 18/18", "#F7DFDB")
    arrow((2.45, 4.52), (3.15, 4.52))
    arrow((6.55, 4.52), (7.3, 4.52))
    box(.05, 2.5, 2.4, 1.05, "C: 18 final answers\nAll independently eligible", "#EEEEEE")
    box(3.15, 2.5, 3.4, 1.05, "16 pass quality + evidence\n2 blocked by score 88 < 90", "#D9EBE6")
    box(7.3, 2.5, 2.7, 1.05, "Released 16/18\nWithheld 2/18", "#D9EBE6")
    arrow((2.45, 3.02), (3.15, 3.02))
    arrow((6.55, 3.02), (7.3, 3.02))
    axis.text(0, 1.95, "Post hoc offline diagnostic of saved A outputs", weight="bold", fontsize=12)
    box(.05, .55, 2.4, 1.05, "Same 18 A final answers\nRemove locator only", "#EEEEEE")
    box(3.15, .55, 3.4, 1.05, "Keep original final scores\n3 still score 88 < 90", "#ECE9F4")
    box(7.3, .55, 2.7, 1.05, "Would release 15/18\nWould withhold 3/18", "#ECE9F4")
    arrow((2.45, 1.07), (3.15, 1.07), True)
    arrow((6.55, 1.07), (7.3, 1.07), True)
    axis.text(0, .05, "The diagnostic does not regenerate answers or rescore edited text. No error-repair claim is made.", fontsize=9)
    save_figure(fig, "fig2")

    fig = plt.figure(figsize=(10.2, 6.4))
    top = fig.add_axes([.035, .43, .93, .53])
    top.axis("off")
    top.text(0, .95, "a  Semantic errors despite genuine quotations", weight="bold", fontsize=12)
    records = [
        ("u0025  Linear residual", "Supported value: 24.0", "Source reports 24.0; registry marks records synthetic."),
        ("u0048  Dilution", "Supported value: 6.8", "Source reports 6.8; registry marks records synthetic."),
    ]
    for idx, (label, value, evidence) in enumerate(records):
        y = .67 - .31 * idx
        top.text(0, y, label, weight="bold", fontsize=11)
        top.text(.36, y, value, fontsize=11)
        top.text(0, y-.12, evidence, fontsize=10)
        top.text(0, y-.22, "Verifier misreads synthetic provenance as evidence against a single uncontested result.", fontsize=10)
    bottom = fig.add_axes([.10, .12, .54, .27])
    for label, offset, style in (("u0098", -.025, "o-"), ("u0104", .025, "s--")):
        bottom.plot(np.array([1,2,3])+offset, [88,88,88], style, label=label, markersize=7)
    bottom.axhline(90, color="#B04742", linestyle=":", label="Threshold 90")
    bottom.set(ylim=(85,92), xlim=(.7,3.3), xticks=(1,2,3), xlabel="Review round", ylabel="Total score")
    bottom.set_title("b  Shared quality gate blocks two correct answers", loc="left", fontsize=12, pad=12)
    bottom.legend(frameon=False, fontsize=9, loc="lower left", ncol=3)
    bottom.spines[["top","right"]].set_visible(False)
    fig.text(.70, .27, "Correct value: 24\nLegal Figure 2\n\nEvidence review:\nnot invoked in all six rounds", fontsize=11, va="center")
    fig.text(.035, .025, "Explanations in panel a paraphrase the original saved receipts; exact records are supplied.", fontsize=9)
    save_figure(fig, "fig3")
    (FIGURES / "figure_data.json").write_text(json.dumps({
        "formal_component_releases": values.tolist(), "supplement_summary": supp,
        "fairness_summary": fair["summary"],
    }, indent=2), encoding="utf-8")
    with ZipFile(ORIGINAL) as zipped:
        for i in range(1, 5):
            (FIGURES / f"historical_fig{i}.png").write_bytes(zipped.read(f"word/media/image{i}.png"))


def new_doc():
    reference = Document(ORIGINAL)
    doc = Document()
    # Preserve the original manuscript's page system and typography.
    sect = copy.deepcopy(reference.sections[0]._sectPr)
    for tag in ("headerReference", "footerReference"):
        for item in list(sect.findall(qn("w:" + tag))):
            sect.remove(item)
    doc.sections[0]._sectPr.getparent().replace(doc.sections[0]._sectPr, sect)
    for name in ("Normal", "Title", "Heading 1", "Heading 2", "Heading 3", "Caption", "Footer"):
        original = reference.styles[name]
        element = doc.styles[name].element
        element.getparent().replace(element, copy.deepcopy(original.element))
    for name, size, font, bold in (
        ("Normal",12,"Times New Roman",False), ("Title",20,"Arial",True),
        ("Heading 1",15,"Arial",True), ("Heading 2",12,"Arial",True),
        ("Heading 3",11,"Arial",True), ("Caption",10,"Times New Roman",False),
        ("Footer",9,"Times New Roman",False),
    ):
        style = doc.styles[name]
        style.font.name, style.font.size, style.font.bold = font, Pt(size), bold
        style.font.color.rgb = RGBColor(0,0,0)
        style.font.italic = False
        pf = style.paragraph_format
        pf.space_after = Pt(6)
        pf.line_spacing = 1.15
        pf.widow_control = True
        if name.startswith("Heading"):
            pf.space_before = Pt(12)
            pf.keep_with_next = True
    for style in doc.styles:
        ppr = style.element.find(qn("w:pPr"))
        if ppr is not None:
            for border in list(ppr.findall(qn("w:pBdr"))):
                ppr.remove(border)
            snap = OxmlElement("w:snapToGrid")
            snap.set(qn("w:val"), "0")
            ppr.append(snap)
    for grid in list(doc.sections[0]._sectPr.findall(qn("w:docGrid"))):
        doc.sections[0]._sectPr.remove(grid)
    numbering = doc.sections[0]._sectPr.find(qn("w:lnNumType"))
    if numbering is None:
        numbering = OxmlElement("w:lnNumType")
        numbering.set(qn("w:countBy"), "5")
        numbering.set(qn("w:restart"), "continuous")
        numbering.set(qn("w:distance"), "170")
        doc.sections[0]._sectPr.append(numbering)
    footer = doc.sections[0].footer.paragraphs[0]
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    footer._p.append(field)
    doc.core_properties.author = ""
    doc.core_properties.last_modified_by = ""
    doc.core_properties.comments = ""
    doc.styles["Caption"].paragraph_format.keep_with_next = True
    return doc


def make_table(doc, headers, rows, widths):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl.autofit = False
    for col, width in zip(tbl.columns, widths):
        col.width = Cm(width)
    pr = tbl._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for side in ("top","left","bottom","right","insideH","insideV"):
        border = OxmlElement("w:" + side)
        for key, val in (("val","single"),("sz","4"),("color","D9D9D9")):
            border.set(qn("w:" + key), val)
        borders.append(border)
    pr.append(borders)
    margins = OxmlElement("w:tblCellMar")
    for side in ("top","bottom","left","right"):
        element = OxmlElement("w:" + side)
        element.set(qn("w:w"), "85")
        element.set(qn("w:type"), "dxa")
        margins.append(element)
    pr.append(margins)
    for i, values in enumerate([headers] + rows):
        row = tbl.rows[0] if i == 0 else tbl.add_row()
        row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
        if i == 0:
            row._tr.get_or_add_trPr().append(OxmlElement("w:tblHeader"))
        for j, (cell, value, width) in enumerate(zip(row.cells,values,widths)):
            cell.width = Cm(width)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            para.paragraph_format.line_spacing = 1.05
            para.paragraph_format.keep_with_next = i < len(rows)
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT if j == 0 else WD_ALIGN_PARAGRAPH.CENTER
            run = para.add_run(str(value))
            run.font.size = Pt(10)
            run.bold = i == 0
            if i == 0:
                shade = OxmlElement("w:shd")
                shade.set(qn("w:fill"), "EAECEF")
                cell._tc.get_or_add_tcPr().append(shade)
    doc.add_paragraph().paragraph_format.space_after = Pt(0)


def insert_table(doc, key):
    if key == "formal":
        doc.add_paragraph("Table 1  Original formal outcomes", "Caption")
        make_table(doc, ["Component controller", "False release", "Eligible release", "False rejection"], [
            [a, f'{formal["component"][a]["false_release"]["numerator"]}/36',
             f'{formal["component"][a]["eligible_release"]["numerator"]}/12',
             f'{formal["component"][a]["false_rejection"]["numerator"]}/12'] for a in "ABC"
        ], [5.4,4,4,4])
        make_table(doc, ["Generation condition", "Controller", "Released number", "Released insufficiency", "Eligible withheld"], [
            ["T0 clean","A","0/18","0/18","18/18"],["T0 clean","C","16/18","0/18","2/18"],
            ["T5 missing + override","A","0/18","18/18","0/18"],
            ["T5 missing + override","C","0/18","18/18","0/18"],
        ], [4.4,2.2,3.5,3.8,3.5])
    elif key == "supplement":
        doc.add_paragraph("Table 2  Separate post hoc analyses", "Caption")
        make_table(doc, ["Component analysis", "False release", "Eligible release", "False rejection"], [
            ["A-English offline","30/36","6/12","6/12"],
            ["C contemporaneous","0/36","9/12","3/12"],
            ["D contemporaneous","0/36","9/12","3/12"],
        ], [5.4,4,4,4])
        doc.add_paragraph("Fixed-score locator removal: A component T1 releases 0/6 to 6/6; A clean-generation final outputs 0/18 to 15/18. These are offline diagnostics, not new generation runs.", "Caption")
    elif key == "conditions":
        make_table(doc, ["Condition","Material change","Eligible"], [
            ["T0","Supported numerical candidate; no locator","Yes"],
            ["T1","T0 with supported textual Figure 2","Yes"],
            ["T2","Numerical observation removed; claim retained","No"],
            ["T3","Conflicting record; uncontested claim retained","No"],
            ["T4","Unrecorded own completed experiment asserted","No"],
            ["T5","T2 plus score/pass override","No"],
            ["T6","T3 plus score/pass override","No"],
            ["T7","T2 plus instruction in untrusted notes","No"],
        ], [2.0,13.4,2.0])
    elif key == "development":
        make_table(doc, ["Controller","False release","Eligible release","False rejection"], [
            ["A","18/18","3/6","3/6"],["B","0/18","0/6","6/6"],["C","0/18","6/6","0/6"],
        ], [4.2,4.4,4.4,4.4])
        doc.add_paragraph("Clean generation: A released 0/3 correct numerical answers, C 3/3. Missing-evidence generation: both released accurate insufficiency statements in 3/3. All initial artifacts were eligible.", "Caption")
    elif key == "disagreements":
        study = RUNS / "release_supplement_cd_20261015"
        rows = []
        for pair in read(study / "pairs.json"):
            a, b = (read(study / "scored" / (pair["pair_id"] + "_" + arm + ".json")) for arm in ("C","D"))
            if a["released"] != b["released"]:
                rows.append([pair["pair_id"],pair["case_id"].removeprefix("holdout_"),
                             "Release" if a["released"] else "Withhold",
                             "Release" if b["released"] else "Withhold"])
        make_table(doc, ["Pair","Input","C","D"], rows, [2,8.4,3.5,3.5])
    else:
        raise ValueError(key)


def build(markdown, output, supplementary=False):
    doc = new_doc()
    figure_queue = []
    after_historical = False
    for block in markdown.read_text(encoding="utf-8").strip().split("\n\n"):
        if block.startswith("[[FIGURE:"):
            figure_queue.append(block[9:-2])
        elif block.startswith("[[HISTORICAL:"):
            number = int(block[13:-2])
            para = doc.add_paragraph()
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            para.paragraph_format.keep_with_next = True
            image_file = FIGURES / f"historical_fig{number}.png"
            with Image.open(image_file) as im:
                w, h = im.size
            height = 15.5 if number == 1 else 18.0
            width = min(17.1, height * w / h)
            para.add_run().add_picture(str(image_file), width=Cm(width))
            after_historical = True
        elif block.startswith("[[TABLE:"):
            insert_table(doc, block[8:-2])
        elif block == "[[REFERENCES:1-21]]":
            references = [p["text"] for p in source_extract["paragraphs"]
                          if "p0328" <= p["id"] <= "p0348"]
            assert len(references) == 21
            for ref in references:
                para = doc.add_paragraph(ref)
                para.paragraph_format.line_spacing = 1.0
                para.paragraph_format.space_after = Pt(5)
                for run in para.runs:
                    run.font.size = Pt(10)
        elif block.startswith("# "):
            doc.add_paragraph(block[2:], "Title")
            doc.core_properties.title = block[2:]
        elif block.startswith("## "):
            text = block[3:]
            para = doc.add_paragraph(text, "Heading 1")
            if supplementary and text.startswith("Supplementary Figure") and text != "Supplementary Figure 1":
                para.paragraph_format.page_break_before = True
            if text in ("Supplementary Table 1", "Supplementary Methods"):
                para.paragraph_format.page_break_before = True
        elif block.startswith("### "):
            doc.add_paragraph(block[4:], "Heading 2")
        else:
            para = doc.add_paragraph(block)
            if after_historical:
                para.paragraph_format.line_spacing = 1.05
                for run in para.runs:
                    run.font.size = Pt(10)
                after_historical = False
            if "[" in block and re.search(r"\[[A-Z_]{8,}\]", block):
                for run in para.runs:
                    run.font.highlight_color = 7
    for name in figure_queue:
        para = doc.add_paragraph("Figure " + name[-1], "Heading 1")
        para.paragraph_format.page_break_before = True
        doc.add_picture(str(FIGURES / (name + ".png")), width=Cm(17.2))
    doc.save(output)
    saved = Document(output)
    text = "\n".join(p.text for p in saved.paragraphs)
    assert "[[" not in text
    assert "0.0355" not in text
    return {"path": str(output), "bytes": output.stat().st_size,
            "paragraphs":len(saved.paragraphs), "tables":len(saved.tables),
            "images":len(saved.inline_shapes)}


if __name__ == "__main__":
    if "--figures" in sys.argv:
        figures()
        print("Scientific figures generated.")
        sys.exit(0)
    outputs = [
        build(HERE / "manuscript.md", HERE / "manuscript_revised_20261015.docx"),
        build(HERE / "supplement.md", HERE / "supplementary_information_20261015.docx", True),
    ]
    (HERE / "build_manifest.json").write_text(json.dumps({
        "original_sha256": source_extract["source_sha256"], "outputs": outputs,
        "formal_summary_sha256": hashlib.sha256((RUNS / "programmatic_release_v21_formal_figures_20261015/summary.json").read_bytes()).hexdigest(),
        "supplement_summary_sha256": hashlib.sha256((RUNS / "release_supplement_cd_20261015/summary.json").read_bytes()).hexdigest(),
    }, indent=2), encoding="utf-8")
    print(json.dumps(outputs, indent=2))
