"""Rebuild the seven current-paper figures offline without changing originals."""

import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path,
                        help="A new directory outside the delivered package")
    parser.add_argument("--pdftoppm", help="Optional path to Poppler pdftoppm")
    args = parser.parse_args()
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe"
    poppler = args.pdftoppm or shutil.which("pdftoppm") or (str(bundled) if bundled.exists() else None)
    if not poppler:
        raise RuntimeError("Install Poppler and put pdftoppm on PATH, or pass --pdftoppm PATH.")
    out = args.out.resolve()
    if out == ROOT or ROOT in out.parents or out.exists():
        raise ValueError("Choose a new output directory outside the package.")
    out.mkdir(parents=True)

    # Execute only the original plotting functions. Skip the final DOCX image
    # extraction, which depends on the author's local historical Word document.
    source = ROOT / "04_code/main_figures/build_documents_original.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef)
                 and node.name in ("save_figure", "figures")]
    assert len(functions) == 2
    function = next(node for node in functions if node.name == "figures")
    assert isinstance(function.body[-1], ast.With)
    assert "ZipFile(ORIGINAL)" in ast.get_source_segment(
        source.read_text(encoding="utf-8"), function.body[-1])
    function.body.pop()
    namespace = {"FIGURES": out / "main", "json": json}
    inputs = ROOT / "04_code/main_figures/inputs"
    for name in ("formal", "supp", "fair", "audit"):
        namespace[name] = read(inputs / (name + ".json"))
    module = ast.fix_missing_locations(ast.Module(body=functions, type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    namespace["figures"]()

    legacy = ROOT / "04_code/supplement_figures"
    sys.path.insert(0, str(legacy))
    import plot_style
    import draw_figure1
    import draw_mechanisms
    import draw_results
    plot_style.ROOT = out / "supplement"
    plot_style.configure()
    data = read(legacy / "data/figure_data.json")
    snapshot = read(legacy / "data/figure1_snapshot.json")
    reports = [draw_figure1.draw(snapshot), draw_mechanisms.figure2(),
               draw_results.figure3(data), draw_results.figure4(data)]
    assert all(not r["out_of_canvas"] and not r["text_overlaps"] for r in reports)

    import numpy as np
    from PIL import Image, ImageDraw
    comparisons, previews = [], []
    original_renders = out / "original_renders"
    original_renders.mkdir()
    pairs = [(out / "main" / f"fig{i}.pdf",
              ROOT / "02_figures/main" / f"Fig{i}.pdf") for i in range(1, 4)]
    pairs += [(out / "supplement/output/pdf" / (r["figure"] + ".pdf"),
               ROOT / "02_figures/supplement" / f"SuppFig{i}.pdf")
              for i, r in enumerate(reports, 1)]
    for generated, original in pairs:
        images = []
        for path in (generated, original):
            prefix = path.with_suffix("") if path == generated else original_renders / original.stem
            subprocess.run([poppler, "-singlefile", "-r", "144", "-png", str(path), str(prefix)],
                           capture_output=True, check=True)
            with Image.open(prefix.with_suffix(".png")) as image:
                images.append(image.convert("RGB"))
        assert images[0].size == images[1].size, generated.name
        difference = np.abs(np.array(images[0], dtype=int) - np.array(images[1], dtype=int))
        comparisons.append({"figure": original.stem, "rendered_size": images[0].size,
                            "mean_absolute_pixel_difference": float(difference.mean()),
                            "identical_rendered_pixels": bool(not np.any(difference))})
        images[0].save(generated.with_suffix(".png"))
        thumbnail = images[0].copy()
        thumbnail.thumbnail((720, 600))
        tile = Image.new("RGB", (760, 650), "white")
        ImageDraw.Draw(tile).text((20, 15), original.stem, fill="black")
        tile.paste(thumbnail, (20, 40))
        previews.append(tile)
    sheet = Image.new("RGB", (3 * 760, 3 * 650), "#eeeeee")
    for i, image in enumerate(previews):
        sheet.paste(image, ((i % 3) * 760, (i // 3) * 650))
    sheet.save(out / "contact_sheet.png")
    result = {"status": "passed", "figures_rebuilt": 7, "model_calls": 0,
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "adaptation": "Original plotting functions; only historical DOCX extraction omitted. Legacy Figure 5 is not invoked.",
              "packages": {n: importlib.metadata.version(n) for n in
                           ("matplotlib", "numpy", "Pillow", "pypdf")},
              "supplement_layout_checks": reports, "render_comparisons": comparisons}
    (out / "figure_reproduction.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
