# -*- coding: utf-8 -*-
"""图片转 PDF 小工具（纯 Pillow，无需 Office / 网络）。

三种用法：
  1) 原图比例（页面大小 = 图片尺寸 / DPI），画面不裁剪、不留白：
     python tools\\img2pdf.py 海报.png
  2) 居中放进 A4 / A3 / A5 / Letter（四周留白，适合家用打印机）：
     python tools\\img2pdf.py 海报.png --page a4
  3) 多张图合成一个 PDF（一张一页）：
     python tools\\img2pdf.py 1.png 2.jpg 3.webp -o 合集.pdf --page a4

常用参数：
  -o / --out      输出路径，缺省与第一张图同名 .pdf
  --dpi           原图比例模式下的物理分辨率，默认 150（数值越大页面越小）
  --margin        A4 等固定页模式的留白，单位毫米，默认 8
  --quality       JPEG 质量，默认 92
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image

# 纸张尺寸：毫米（宽, 高），竖版
PAGE_SIZES = {
    "a5": (148.0, 210.0),
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "letter": (215.9, 279.4),
}

# 固定纸张时画布的像素密度。取 200：常见手机照片（4000px+）缩到纸面后
# 仍是约 200dpi 的打印质量；而比纸面小的图不会被放大，保持原始像素。
PAGE_DPI = 200


def flatten(im: Image.Image) -> Image.Image:
    """统一转成白底 RGB：透明 PNG / 调色板图都不会变黑底。"""
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    if im.mode == "RGB":
        return im
    if im.mode == "P" and "transparency" in im.info:
        return flatten(im.convert("RGBA"))
    return im.convert("RGB")


def place_on_page(im: Image.Image, page: str, margin_mm: float) -> tuple[Image.Image, tuple[int, int]]:
    """把图片等比缩放后居中贴到固定尺寸纸面画布上，不裁剪、不放大。

    返回 (画布, 图片落版后的像素尺寸)。
    """
    w_mm, h_mm = PAGE_SIZES[page]
    canvas_w = max(1, round(w_mm / 25.4 * PAGE_DPI))
    canvas_h = max(1, round(h_mm / 25.4 * PAGE_DPI))
    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    margin_px = round(margin_mm / 25.4 * PAGE_DPI)
    avail_w = max(1, canvas_w - 2 * margin_px)
    avail_h = max(1, canvas_h - 2 * margin_px)

    # 只缩小不放大：小图保持原始像素，避免糊成一片
    scale = min(avail_w / im.width, avail_h / im.height, 1.0)
    new_w = max(1, round(im.width * scale))
    new_h = max(1, round(im.height * scale))
    resized = im if (new_w, new_h) == im.size else im.resize((new_w, new_h), Image.LANCZOS)

    canvas.paste(resized, ((canvas_w - new_w) // 2, (canvas_h - new_h) // 2))
    return canvas, (new_w, new_h)


def build_pdf(
    inputs: list[Path],
    out: Path,
    page: str,
    dpi: int,
    margin_mm: float,
    quality: int,
) -> None:
    pages: list[Image.Image] = []
    placed_sizes: list[tuple[int, int]] = []

    for path in inputs:
        with Image.open(path) as raw:
            raw.load()
            im = flatten(raw)
            if page == "auto":
                pages.append(im.copy())
                placed = im.size
            else:
                canvas, placed = place_on_page(im, page, margin_mm)
                pages.append(canvas)

            placed_sizes.append(placed)

    out.parent.mkdir(parents=True, exist_ok=True)
    first, rest = pages[0], pages[1:]

    # 固定纸张时按画布像素反推分辨率，让 MediaBox 尽量等于标准 A4/A3（误差 < 0.1pt）
    if page == "auto":
        resolution = float(dpi)
    else:
        resolution = first.width / (PAGE_SIZES[page][0] / 25.4)

    first.save(
        out,
        "PDF",
        resolution=resolution,
        quality=quality,
        save_all=True,
        append_images=rest,
    )

    notes = []
    for i, placed in enumerate(placed_sizes, 1):
        w_mm = placed[0] / resolution * 25.4
        h_mm = placed[1] / resolution * 25.4
        notes.append(
            f"  第 {i} 页：{placed[0]}x{placed[1]}px"
            f"  →  {w_mm / 10:.1f}x{h_mm / 10:.1f} cm"
            f"（约 {placed[0] / (w_mm / 25.4):.0f} dpi）"
        )

    size_mb = out.stat().st_size / 1024 / 1024
    print("\n".join(notes))
    print(f"已生成：{out}  ({size_mb:.2f} MB, 共 {len(pages)} 页)")


def main() -> int:
    ap = argparse.ArgumentParser(description="把图片输出为 PDF")
    ap.add_argument("inputs", nargs="+", type=Path, help="图片路径（可多张）")
    ap.add_argument("-o", "--out", type=Path, help="输出 PDF 路径")
    ap.add_argument(
        "--page",
        default="auto",
        choices=["auto", *PAGE_SIZES],
        help="auto=页面跟随图片比例；a4/a3/a5/letter=固定纸张并居中留白",
    )
    ap.add_argument("--dpi", type=int, default=150, help="auto 模式纸张分辨率，默认 150")
    ap.add_argument("--margin", type=float, default=8.0, help="固定纸张模式留白（毫米），默认 8")
    ap.add_argument("--quality", type=int, default=92, help="JPEG 质量，默认 92")
    args = ap.parse_args()

    missing = [str(p) for p in args.inputs if not p.is_file()]
    if missing:
        print("找不到图片：" + "、".join(missing))
        return 1
    if args.dpi <= 0 or args.quality < 1:
        print("--dpi / --quality 必须为正数")
        return 1

    out = args.out or args.inputs[0].with_suffix(".pdf")
    build_pdf(args.inputs, out, args.page, args.dpi, args.margin, args.quality)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
