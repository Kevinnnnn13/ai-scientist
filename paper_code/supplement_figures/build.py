"""Rebuild the five figures from a frozen snapshot; no experiments or new tests."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont, ImageOps
from pypdf import PdfReader

from plot_style import ROOT, PALETTE, WIDTH, configure, write_json
from draw_figure1 import draw as figure1
from draw_mechanisms import figure2
from draw_results import figure3, figure4, figure5


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def validate(data):
    assert len(data["pilot"]) == 72
    assert len({(r["condition_id"], r["question_id"]) for r in data["pilot"]}) == 72
    counts = Counter(r["plan_status"] for r in data["pilot"])
    assert counts == {"in_progress": 53, "validated": 13, "ungated": 6}, counts
    assert [r["hypothesis_score"] for r in data["case"]["rounds"]] == [65, 69, 71, 72, 72, 70, 70]
    assert [r["data_score"] for r in data["case"]["rounds"]] == [74, 74, 74, 74, 80, 84, 84]
    assert len(data["case"]["issues"]) == 10
    assert all(len(r["statuses"]) == 7 for r in data["case"]["issues"])
    assert Counter(r["statuses"][-1] for r in data["case"]["issues"]) == {"active": 9, "resolved": 1}
    assert len(data["repair_pairs"]) == 6
    for row in data["repair_pairs"]:
        assert row["before_status"] == "validated" and row["after_status"] == "in_progress"
        assert row["before_score"] == row["after_score"]
        assert row["before_data_score"] == row["after_data_score"] == 100
        assert row["terminal_state"] == row["postrun_failure"] == 1
    assert len(data["ratings"]) == 5 and all(r["n"] == 20 for r in data["ratings"])
    assert not any(r["significant_holm_0_05"] for r in data["ratings"])
    assert len(data["preferences"]) == 3
    assert all(r["processed"] + r["unprocessed"] == 20 for r in data["preferences"])
    assert [r["item"] for r in data["preferences"] if r["significant_holm_0_05"]] == ["readability_preference"]
    assert data["inference"]["new_statistical_tests_run"] is False
    return {"pilot_cells": 72, "pilot_state_counts": dict(counts), "repair_pairs": 6,
            "case_rounds": 7, "case_issues": 10, "rating_items": 5,
            "preference_items": 3, "participants": 20, "new_statistical_tests_run": False,
            "all_data_invariants_pass": True}


def inspect_pdf(pdf):
    reader = PdfReader(pdf)
    assert len(reader.pages) == 1
    page = reader.pages[0]
    assert abs(float(page.mediabox.width)-WIDTH) < 0.01
    fonts = []
    for reference in page["/Resources"].get("/Font", {}).values():
        font = reference.get_object()
        descendants = font.get("/DescendantFonts", [font])
        for descendant in descendants:
            actual = descendant.get_object()
            descriptor = actual.get("/FontDescriptor")
            embedded = bool(descriptor and any(k in descriptor.get_object() for k in ["/FontFile", "/FontFile2", "/FontFile3"]))
            fonts.append({"font": str(actual.get("/BaseFont")), "embedded": embedded})
    assert fonts and all(item["embedded"] for item in fonts)
    xobjects = page["/Resources"].get("/XObject", {})
    images = [str(name) for name, obj in xobjects.items() if obj.get_object().get("/Subtype") == "/Image"]
    assert not images, images
    svg = ROOT / "output/svg" / (pdf.stem + ".svg")
    svg_content = svg.read_text(encoding="utf-8")
    assert "<text" in svg_content and "<image" not in svg_content
    return {"pages": 1, "width_mm": round(float(page.mediabox.width)/72*25.4, 5),
            "height_mm": round(float(page.mediabox.height)/72*25.4, 3),
            "fonts": fonts, "raster_images": images, "svg_live_text": True,
            "extractable_text_characters": len(page.extract_text())}


def find_poppler(explicit):
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
    candidate = explicit or os.environ.get("PDFTOPPM") or shutil.which("pdftoppm")
    if candidate:
        return str(candidate)
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("Install Poppler and put pdftoppm on PATH, or pass --pdftoppm PATH.")


def previews(stems):
    output = ROOT / "output" / "previews"
    output.mkdir(parents=True, exist_ok=True)
    font_path = Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 23) if font_path.exists() else ImageFont.load_default()
    images = []
    names = ["Evidence-linked workflow", "Core mechanisms", "Recorded case", "Pilot and intervention", "Reader evaluation"]
    for i, stem in enumerate(stems):
        original = Image.open(ROOT / "output/pdf" / f"{stem}.png").convert("RGB")
        small = original.resize((1100, round(original.height * 1100/original.width)), Image.Resampling.LANCZOS)
        small.save(output / f"{stem}_preview.png")
        ImageOps.grayscale(small).save(output / f"{stem}_grayscale.png")
        publication = original.resize((850, round(original.height*850/original.width)), Image.Resampling.LANCZOS)
        publication.save(output / f"{stem}_publication_width.png")
        thumb = original.resize((570, round(original.height * 570/original.width)), Image.Resampling.LANCZOS)
        images.append(thumb)
    cell_h = max(im.height for im in images) + 78
    sheet = Image.new("RGB", (3*606+18, 2*cell_h+18), "#E8ECEF")
    draw = ImageDraw.Draw(sheet)
    for i, image in enumerate(images):
        x, y = 18+(i%3)*606, 18+(i//3)*cell_h
        draw.rectangle((x, y, x+588, y+cell_h-18), fill="white")
        draw.text((x+12, y+12), f"{i+1}  {names[i]}", font=font, fill=PALETTE["ink"])
        sheet.paste(image, (x+9, y+48))
    x, y = 18+2*606, 18+cell_h
    draw.text((x+20, y+28), "MANUSCRIPT FIGURES / V3", font=font, fill=PALETTE["ink"])
    regular_path = Path("C:/Windows/Fonts/arial.ttf")
    regular = ImageFont.truetype(str(regular_path), 21) if regular_path.exists() else ImageFont.load_default()
    for j, label in enumerate(["Labels reconciled with source code", "Aligned review scores + issue traces",
                               "180 mm vector PDF and editable SVG", "Complete plotting code and frozen data",
                               "Full-size PDFs are the publication masters"]):
        draw.text((x+20, y+83+j*40), label, font=regular, fill=PALETTE["muted"])
    sheet.save(ROOT / "preview_contact_sheet.png")


def compare_versions(reference, stems):
    font_path = Path("C:/Windows/Fonts/arialbd.ttf")
    font = ImageFont.truetype(str(font_path), 27) if font_path.exists() else ImageFont.load_default()
    destination = ROOT / "output/comparisons"
    destination.mkdir(parents=True, exist_ok=True)
    for stem in stems[1:]:
        sources = [reference / "output/pdf" / (stem+".png"), ROOT / "output/pdf" / (stem+".png")]
        images = []
        for path in sources:
            image = Image.open(path).convert("RGB")
            images.append(image.resize((1020, round(image.height*1020/image.width)), Image.Resampling.LANCZOS))
        height = max(image.height for image in images)+90
        sheet = Image.new("RGB", (2094, height), "#E8ECEF")
        draw = ImageDraw.Draw(sheet)
        for i, image in enumerate(images):
            x = 18+i*1038
            draw.rectangle((x, 18, x+1020, height-18), fill="white")
            draw.text((x+14, 28), ["Previous / v2", "New / v3"][i], font=font, fill=PALETTE["ink"])
            sheet.paste(image, (x, 70))
        sheet.save(destination / (stem+"_v2_v3.png"))


def validate_inputs(reference_suite=None, accepted_figure1=None):
    provenance = ROOT / "input_provenance.json"
    if reference_suite:
        assert accepted_figure1, "Supply the accepted Figure 1 directory with the reference suite."
        entries = {}
        for path in sorted((ROOT / "data").iterdir()):
            source_dir = accepted_figure1 if path.name == "figure1_snapshot.json" else reference_suite
            source = source_dir / "data" / path.name
            assert source.is_file(), source
            assert sha256(source) == sha256(path), path.name
            entries[path.relative_to(ROOT).as_posix()] = {"sha256": sha256(path), "reference_path": str(source)}
        write_json(provenance, {"inputs": entries, "all_inputs_copied_without_modification": True})
    manifest = json.loads(provenance.read_text(encoding="utf-8"))
    actual_names = {p.relative_to(ROOT).as_posix() for p in (ROOT / "data").iterdir() if p.is_file()}
    assert actual_names == set(manifest["inputs"])
    for name, expected in manifest["inputs"].items():
        assert sha256(ROOT / name) == expected["sha256"], name
    assert sha256(ROOT / "data/figure_data.json") == "0E67F68D80F7E587C3C386BEE33AC726240EF6A89DB34220C6A591743A631116"
    return {"verified_frozen_input_files": len(actual_names), "all_frozen_input_hashes_match": True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-suite", type=Path, help="One-time provenance verification against the v2 suite")
    parser.add_argument("--accepted-figure1", type=Path, help="One-time provenance verification against accepted Figure 1")
    parser.add_argument("--compare-with", type=Path, help="Optional v2 directory; only needed to recreate comparison sheets")
    parser.add_argument("--require-accepted-bytes", action="store_true", help="Require byte-identical Figure 1; needs the recorded font/runtime versions")
    parser.add_argument("--pdftoppm", help="Path to Poppler pdftoppm")
    parser.add_argument("--dpi", type=int, default=300, help="Preview PNG resolution; PDF/SVG remain vector")
    args = parser.parse_args()
    input_checks = validate_inputs(args.reference_suite, args.accepted_figure1)
    snapshot = ROOT / "data/figure_data.json"
    data = json.loads(snapshot.read_text(encoding="utf-8"))
    validation = validate(data)
    validation.update(input_checks)
    architecture = json.loads((ROOT / "data/figure1_snapshot.json").read_text(encoding="utf-8"))
    assert len(architecture["sources"]) == 22 and len(architecture["concepts"]) == 7
    assert len(architecture["links"]) == 28
    assert [row["source_assignments"] for row in architecture["concepts"]] == [10, 0, 3, 2, 3, 6, 4]
    font_family = configure()
    reports = [figure1(architecture), figure2(), figure3(data), figure4(data), figure5(data)]
    write_json(ROOT / "layout_checks.json", reports)
    errors = [r for r in reports if r["out_of_canvas"] or r["text_overlaps"]]
    stems = [r["figure"] for r in reports]
    poppler = find_poppler(args.pdftoppm)
    pdf_checks = {}
    for stem in stems:
        pdf = ROOT / "output/pdf" / f"{stem}.pdf"
        pdf_checks[stem] = inspect_pdf(pdf)
        subprocess.run([poppler, "-singlefile", "-r", str(args.dpi), "-png", str(pdf), str(pdf.with_suffix(""))],
                       check=True, capture_output=True)
    previews(stems)
    if args.compare_with:
        compare_versions(args.compare_with, stems)
    accepted_pdf_hash = "FFB3A88C62ACBF9B816E024603293927A8655BCCCFE5EF828ABF6FD5A589BE6D"
    current_figure1_hash = sha256(ROOT / "output/pdf" / (stems[0]+".pdf"))
    accepted_unchanged = current_figure1_hash == accepted_pdf_hash
    if args.require_accepted_bytes:
        assert accepted_unchanged, "Accepted Figure 1 changed during integration."
    packages = {name: importlib.metadata.version(name) for name in ["matplotlib", "numpy", "Pillow", "pypdf"]}
    write_json(ROOT / "runtime_versions.json", {"python": platform.python_version(), "packages": packages,
               "font": font_family, "platform": platform.platform(), "preview_dpi": args.dpi,
               "poppler": poppler, "build_time_utc": datetime.now(timezone.utc).isoformat()})
    write_json(ROOT / "palette.json", PALETTE)
    validation.update({"snapshot_sha256": sha256(snapshot), "pdf_checks": pdf_checks,
                       "layout_checks_pass": not errors,
                       "accepted_figure1_pdf_unchanged": accepted_unchanged,
                       "accepted_figure1_pdf_sha256": current_figure1_hash,
                       "visual_inspection": "See visual_review.md for the human-visible PDF render inspection."})
    write_json(ROOT / "verification_report.json", validation)
    (ROOT / "requirements.txt").write_text("\n".join(f"{name}=={version}" for name, version in packages.items())+"\n", encoding="ascii")
    print(json.dumps({"figures": stems, "layout_problems": errors, "snapshot_sha256": sha256(snapshot)}, indent=2))
    if errors:
        raise SystemExit("Layout check failed; renders retained for inspection.")


if __name__ == "__main__":
    main()
