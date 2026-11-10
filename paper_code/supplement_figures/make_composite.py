"""Arrange the five checked figures without cropping or changing their data."""
from pathlib import Path
import hashlib
import json
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
STEMS = [
    "figure1_evidence_workflow_v3", "figure2_core_mechanisms",
    "figure3_real_run_case", "figure4_faults_and_repair",
    "figure5_reader_evaluation",
]
TITLES = [
    "Evidence-linked workflow", "Core mechanisms", "Recorded review trajectory",
    "Pilot and blocking intervention", "Exploratory reader evaluation",
]


def font(size, bold=False):
    win = Path("C:/Windows/Fonts") / ("arialbd.ttf" if bold else "arial.ttf")
    if win.exists():
        return ImageFont.truetype(str(win), size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf", size)


def main():
    images = [Image.open(ROOT / "output/pdf" / (stem + ".png")).convert("RGB") for stem in STEMS]
    width, margin, gap = 6000, 100, 100
    header, label_height, row_gap, bottom = 220, 100, 150, 110
    first_width = (width - margin * 2 - gap) // 2
    second_width = (width - margin * 2 - gap * 2) // 3
    widths = [first_width] * 2 + [second_width] * 3
    resized = [im.resize((w, round(im.height * w / im.width)), Image.Resampling.LANCZOS)
               for im, w in zip(images, widths)]
    first_height = max(im.height for im in resized[:2]) + label_height
    second_y = header + first_height + row_gap
    height = second_y + max(im.height for im in resized[2:]) + label_height + bottom
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)
    draw.text((margin, 60), "AI Scientist", font=font(64, True), fill="#202B33")
    draw.text((width - margin, 78), "FIVE MANUSCRIPT FIGURES  |  13 OCTOBER 2026",
              font=font(32), fill="#57636D", anchor="ra")
    placements = []
    for i, (image, title) in enumerate(zip(resized, TITLES)):
        x = margin + (i if i < 2 else i - 2) * ((first_width if i < 2 else second_width) + gap)
        y = header if i < 2 else second_y
        draw.text((x, y), f"{i + 1:02d}", font=font(44, True), fill="#3C5488")
        draw.text((x + 85, y + 4), title, font=font(37, True), fill="#202B33")
        sheet.paste(image, (x, y + label_height))
        placements.append({"figure": i + 1, "x": x, "y": y + label_height,
                           "width": image.width, "height": image.height,
                           "source": STEMS[i] + ".png",
                           "source_sha256": hashlib.sha256((ROOT / "output/pdf" / (STEMS[i] + ".png")).read_bytes()).hexdigest()})
    draw.line((margin, second_y - row_gap // 2, width - margin, second_y - row_gap // 2),
              fill="#DCE1E4", width=3)
    destination = ROOT.parent / "figures_overview.png"
    sheet.save(destination, dpi=(300, 300), optimize=True)
    qa = ROOT.parent / "qa"
    qa.mkdir(exist_ok=True)
    preview = sheet.resize((1800, round(height * 1800 / width)), Image.Resampling.LANCZOS)
    preview.save(qa / "figures_overview_preview.jpg", quality=95, subsampling=0)
    (qa / "composite_manifest.json").write_text(json.dumps({"width": width, "height": height,
        "placements": placements, "crops": False, "data_changes": False}, indent=2) + "\n", encoding="utf-8")
    print(destination)
    print(f"{width} x {height} pixels")


if __name__ == "__main__":
    main()
