#!/usr/bin/env python3
"""Generate the mcabridge logo + app icons (reproducible, Pillow only).

Design: Brooklyn Bridge tower with a glowing gothic archway; a black cat's
face silhouetted inside it, two neon-green eyes. Flanking towers and a
suspension span frame it. Drawn at 4x supersample for clean edges, masked
to the rounded app tile, dithered to avoid gradient banding.

The old walking-cat-on-bridge mark was retired: too small to read at icon
sizes. This one keeps exactly two scale-robust elements (black cat head on
a bright arch + green eyes); the thin cables are decoration that fades out
gracefully at 16 px without leaving stray marks.

Writes:
    mcabridge/assets/logo.png   1024x1024 master
    mcabridge/assets/app.ico    Windows icon (multi-size)
    mcabridge/assets/app.icns   macOS icon bundle

Run:  python tools/gen_logo.py
"""
import math
import os
import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

S = 4                       # supersample factor
W = H = 1024
SS = W * S

BG_TOP = (13, 20, 32)
BG_BOT = (22, 42, 70)
BLUE = (78, 161, 255)
GREEN = (89, 247, 160)
STONE = (99, 132, 176)
STONE_EDGE = (168, 205, 242)
BLACKCAT = (7, 11, 19)


def tile_base():
    """Full-bleed rounded app tile with dithered vertical navy gradient."""
    grad = Image.new("RGB", (SS, SS))
    gd = ImageDraw.Draw(grad)
    for y in range(SS):
        t = y / (SS - 1)
        c = tuple(int(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOT))
        gd.line([(0, y), (SS, y)], fill=c)
    rnd = random.Random(7)
    px = grad.load()
    for y in range(0, SS, 3):
        for x in range(0, SS, 3):
            n = rnd.randint(-3, 3)
            r, g, b = px[x, y]
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)),
                        max(0, min(255, b + n)))
    img = grad.convert("RGBA")
    mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [10 * S, 10 * S, SS - 11 * S, SS - 11 * S], radius=178 * S, fill=255)
    img.putalpha(mask)
    return img


def gothic_path(cx, half_w, apex_y, spring_y, base_y, n=40, powr=1.75):
    """Pointed-arch (ogive) outline polygon."""
    pts = [(cx - half_w, base_y), (cx - half_w, spring_y)]
    for i in range(n + 1):
        t = i / n
        x = (cx - half_w) + half_w * t
        y = spring_y - (spring_y - apex_y) * (t ** powr)
        pts.append((x, y))
    right = [(2 * cx - x, y) for x, y in reversed(pts[1:-1])]
    pts += right + [(cx + half_w, base_y)]
    return pts


def add_glow(base, layer, blur, gain):
    glow = layer.filter(ImageFilter.GaussianBlur(blur * S))
    glow = glow.point(lambda v: int(v * gain))
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.alpha_composite(base)
    out.alpha_composite(glow)
    out.alpha_composite(layer)
    return out


def finish(img):
    """Clip to the tile shape, add a subtle border stroke, downsample."""
    mask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [10 * S, 10 * S, SS - 11 * S, SS - 11 * S], radius=178 * S, fill=255)
    r, g, b, a = img.split()
    a = ImageChops.multiply(a, mask)
    img = Image.merge("RGBA", (r, g, b, a))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([10 * S + 2, 10 * S + 2, SS - 13 * S, SS - 13 * S],
                        radius=176 * S, outline=(96, 140, 190, 150), width=3 * S)
    return img.resize((W, H), Image.LANCZOS)


def build():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(here, "mcabridge", "assets")
    os.makedirs(assets, exist_ok=True)

    img = tile_base()
    tx = SS // 2
    deck_y = int(0.845 * SS)

    # shared anchors: everything connects to these
    cap_top = int(0.150 * SS)
    half = int(0.205 * SS)                        # main tower half-width
    t1x, t2x = int(0.165 * SS), int(0.835 * SS)   # flanking tower centers
    ftw = int(0.030 * SS)
    ftop = int(0.27 * SS)                         # flanking tower top y

    # cables FIRST (behind solids). Continuous: off-tile -> t1 top -> sag
    # -> t2 top -> off-tile; stay ends run below the deck / past the tile
    # edge so the mask clips them (no floating terminations).
    cables = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cables)

    def stay(x0, y0, x1, y1, bend=2.4):
        return [(x0 + (x1 - x0) * (i / 39), y0 + (y1 - y0) * ((i / 39) ** bend))
                for i in range(40)]

    left_stay = list(reversed(stay(-40 * S, deck_y + 26 * S, t1x, ftop)))
    right_stay = stay(t2x, ftop, SS + 40 * S, deck_y + 26 * S)
    span = [(t1x + (t2x - t1x) * (i / 120),
             ftop + int(0.30 * SS) * 4 * (i / 120) * (1 - i / 120))
            for i in range(121)]
    cd.line(left_stay + span + right_stay, fill=BLUE, width=12 * S, joint="curve")
    # hangers from main cable to deck (skip where the main tower covers)
    for i in range(1, 16):
        t = i / 16
        x = int(t1x + (t2x - t1x) * t)
        if abs(x - tx) < half + 4 * S:
            continue
        ytop = ftop + int(0.30 * SS) * 4 * t * (1 - t)
        cd.line([(x, ytop), (x, deck_y)], fill=BLUE, width=6 * S)
    img.alpha_composite(cables)

    # flanking towers
    d = ImageDraw.Draw(img)
    for fx in (t1x, t2x):
        d.rectangle([fx - ftw, ftop, fx + ftw, deck_y], fill=(46, 70, 104, 255))
        d.rectangle([fx - ftw - 8 * S, ftop - 14 * S, fx + ftw + 8 * S, ftop],
                    fill=(46, 70, 104, 255))
        d.rectangle([fx + ftw - 5 * S, ftop, fx + ftw, deck_y],
                    fill=(96, 132, 176, 255))

    # main tower with cap and full-height edge highlights
    d.rectangle([tx - half, cap_top + int(0.014 * SS), tx + half, deck_y], fill=STONE)
    d.rectangle([tx - half - int(0.030 * SS), cap_top,
                 tx + half + int(0.030 * SS), cap_top + int(0.014 * SS)], fill=STONE)
    d.rectangle([tx - half - int(0.030 * SS), cap_top,
                 tx + half + int(0.030 * SS), cap_top + 6 * S], fill=STONE_EDGE)
    d.rectangle([tx - half, cap_top + int(0.014 * SS), tx - half + 9 * S, deck_y],
                fill=STONE_EDGE)
    d.rectangle([tx + half - 9 * S, cap_top + int(0.014 * SS), tx + half, deck_y],
                fill=STONE_EDGE)

    # glowing archway (moonlight through the tower)
    aw = int(half * 0.56)
    apex = int(0.345 * SS)
    spring = int(0.545 * SS)
    apoly = gothic_path(tx, aw, apex, spring, deck_y)

    glowbg = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ImageDraw.Draw(glowbg).polygon(
        gothic_path(tx, int(aw * 1.24), apex - int(0.045 * SS),
                    spring - int(0.018 * SS), deck_y),
        fill=(130, 220, 255, 160))
    img = add_glow(img, glowbg, blur=28, gain=0.9)

    grad = Image.new("RGB", (SS, SS), (235, 248, 255))
    gd2 = ImageDraw.Draw(grad)
    for y in range(SS):
        t = y / (SS - 1)
        gd2.line([(0, y), (SS, y)],
                 fill=(int(238 - 95 * t), int(249 - 72 * t), 255))
    amask = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(amask).polygon(apoly, fill=255)
    arch_layer = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    arch_layer.paste(grad, (0, 0), amask)
    img.alpha_composite(arch_layer)

    # uniform rim stroke around the arch
    outer = Image.new("L", (SS, SS), 0)
    ImageDraw.Draw(outer).polygon(
        gothic_path(tx, aw + int(0.013 * SS), apex - int(0.018 * SS), spring, deck_y),
        fill=255)
    rim = ImageChops.subtract(outer, amask)
    img.paste(Image.new("RGBA", (SS, SS), STONE_EDGE + (255,)), (0, 0), rim)

    # black cat face centered in the arch; ears fuse into the head silhouette
    d = ImageDraw.Draw(img)
    cy = int(0.60 * SS)
    hs = int(0.112 * SS)
    d.polygon([(tx - hs * 0.72, cy - hs * 0.5), (tx - hs * 0.14, cy - hs * 0.86),
               (tx - hs * 0.95, cy - hs * 1.62)], fill=BLACKCAT)
    d.polygon([(tx + hs * 0.72, cy - hs * 0.5), (tx + hs * 0.14, cy - hs * 0.86),
               (tx + hs * 0.95, cy - hs * 1.62)], fill=BLACKCAT)
    d.ellipse([tx - hs, cy - hs, tx + hs, cy + hs], fill=BLACKCAT)
    d.ellipse([tx - hs * 1.1, cy - hs * 0.06, tx + hs * 1.1, cy + hs * 0.72],
              fill=BLACKCAT)

    # two DISTINCT level glowing eyes with a clear gap
    eyer = Image.new("RGBA", (SS, SS), (0, 0, 0, 0))
    ed = ImageDraw.Draw(eyer)
    erx, ery, edx = int(hs * 0.30), int(hs * 0.19), int(hs * 0.48)
    for sgn in (-1, 1):
        ex = tx + sgn * edx
        eyc = cy - int(0.075 * SS)
        ed.ellipse([ex - erx, eyc - ery, ex + erx, eyc + ery], fill=GREEN)
    img = add_glow(img, eyer, blur=10, gain=0.85)

    # deck band with top highlight (tile mask clips the corners)
    d = ImageDraw.Draw(img)
    d.rectangle([0, deck_y, SS, SS], fill=(16, 28, 46, 255))
    d.line([(0, deck_y), (SS, deck_y)], fill=BLUE, width=7 * S)

    out = finish(img)
    master = os.path.join(assets, "logo.png")
    out.save(master)
    print("wrote", master)

    out.save(os.path.join(assets, "app.ico"),
             sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    print("wrote app.ico")
    out.save(os.path.join(assets, "app.icns"))
    print("wrote app.icns")


if __name__ == "__main__":
    build()
