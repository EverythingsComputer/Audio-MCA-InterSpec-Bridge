#!/usr/bin/env python3
"""Derive mcabridge app icons from the logo master artwork (Pillow only).

The master is mcabridge/assets/logo.png — the Brooklyn-bridge-with-black-cat
artwork provided by the project author. This tool derives the per-platform
app icons from it:

    mcabridge/assets/logo.png   1024x1024 master (normalized, square)
    mcabridge/assets/app.ico    Windows icon (multi-size, square)
    mcabridge/assets/app.icns   macOS icon bundle — artwork gets rounded
                                corners + padding per Apple's icon grid
                                (third-party icons are NOT auto-rounded by
                                macOS; a full-bleed square looks wrong in
                                the Dock next to native apps)

Usage:
    python tools/gen_logo.py [source.png]

With no argument, re-derives from the current logo.png. To install new
artwork:  python tools/gen_logo.py ~/path/to/new-icon.png
"""
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "mcabridge", "assets")


def load_square(im: Image.Image) -> Image.Image:
    """Pad a near-square image to an exact square without distortion."""
    im = im.convert("RGBA")
    w, h = im.size
    if w != h:
        side = max(w, h)
        canvas = Image.new("RGBA", (side, side))
        canvas.paste(im, ((side - w) // 2, (side - h) // 2))
        # fill slivers with edge pixels so no transparent fringe appears
        canvas.paste(im.crop((0, 0, 1, h)), (0, (side - h) // 2))
        canvas.paste(im.crop((w - 1, 0, w, h)), (side - 1, (side - h) // 2))
        im = canvas
    return im


def rounded(im: Image.Image, radius_frac: float) -> Image.Image:
    """Round the corners (macOS-style squircle approximation)."""
    w, _ = im.size
    r = int(w * radius_frac)
    mask = Image.new("L", (w, w), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, w - 1], radius=r, fill=255)
    out = im.copy()
    out.putalpha(mask)
    return out


def build(src: str | None = None) -> None:
    os.makedirs(ASSETS, exist_ok=True)
    master_path = os.path.join(ASSETS, "logo.png")
    src = src or master_path

    art = load_square(Image.open(src))

    # --- logo.png master at 1024 (runtime window/taskbar icon)
    logo = art.resize((1024, 1024), Image.LANCZOS) if art.size != (1024, 1024) else art
    logo.save(master_path)
    print("wrote", master_path)

    # --- app.ico: Windows, square artwork, multi-size
    logo.save(os.path.join(ASSETS, "app.ico"),
              sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote app.ico")

    # --- app.icns: macOS grid — art occupies ~81% of the canvas with rounded
    # corners; Pillow's icns writer emits all standard variants (ic07..ic14).
    pad = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    inner = rounded(logo.resize((832, 832), Image.LANCZOS), 0.185)
    pad.paste(inner, (96, 96), inner)
    pad.save(os.path.join(ASSETS, "app.icns"))
    print("wrote app.icns")


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else None)
