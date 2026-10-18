#!/usr/bin/env python3
"""Generate the mcabridge logo + app icons (reproducible, Pillow only).

A neon-green cat silhouette walking across a Brooklyn-Bridge-style suspension
bridge, transparent background. Writes:

    assets/logo.png        1024x1024 master
    assets/app.ico         Windows icon (multi-size)
    assets/app.icns        macOS icon bundle

Run:  python tools/gen_logo.py
"""
import os
from PIL import Image, ImageDraw, ImageFilter

W = H = 1024
GREEN = (96, 255, 160)
BLUE = (96, 170, 255)

DECK_Y = 760            # deck surface line
TOWER_XS = (300, 724)
TOWER_TOP = 150


def parab(p0, p1, sag, n=96):
    """Points along a parabola from p0 to p1; sag>0 bows downward at mid."""
    pts = []
    for i in range(n + 1):
        t = i / n
        x = p0[0] + (p1[0] - p0[0]) * t
        y = p0[1] + (p1[1] - p0[1]) * t + sag * 4 * t * (1 - t)
        pts.append((x, y))
    return pts


def bezier(p0, c0, c1, p1, n=64):
    pts = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u**2 * t * c0[0] + 3 * u * t**2 * c1[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u**2 * t * c0[1] + 3 * u * t**2 * c1[1] + t**3 * p1[1]
        pts.append((x, y))
    return pts


def draw_bridge(d):
    tx0, tx1 = TOWER_XS
    # main-span cable: smooth sag between tower tops
    mid_span = parab((tx0, TOWER_TOP + 46), (tx1, TOWER_TOP + 46), 380)
    d.line(mid_span, fill=BLUE, width=10, joint="curve")
    # side-span backstays sweep from tower tops down past the frame edges
    left = bezier((tx0, TOWER_TOP + 46), (tx0 - 150, TOWER_TOP + 60),
                  (120, 430), (-60, DECK_Y - 4))
    right = bezier((tx1, TOWER_TOP + 46), (tx1 + 150, TOWER_TOP + 60),
                   (W - 120, 430), (W + 60, DECK_Y - 4))
    d.line(left, fill=BLUE, width=10, joint="curve")
    d.line(right, fill=BLUE, width=10, joint="curve")

    def cable_y(x):
        seq = mid_span if tx0 <= x <= tx1 else (left if x < tx0 else right)
        best = min(seq, key=lambda p: abs(p[0] - x))
        return best[1]

    # suspender cables hang DOWN from the cable to the deck
    for x in range(40, W - 20, 56):
        if any(abs(x - tx) < 40 for tx in TOWER_XS):
            continue
        y = cable_y(x)
        d.line([(x, y), (x, DECK_Y)], fill=BLUE, width=3)

    # gothic towers with twin pointed arches
    for tx in TOWER_XS:
        tw = 66
        d.rectangle([tx - tw, TOWER_TOP + 40, tx + tw, DECK_Y + 26], fill=BLUE)
        for sgn in (-1, 1):
            cx = tx + sgn * tw * 0.5
            d.polygon([(cx - tw * 0.46, TOWER_TOP + 46),
                       (cx + tw * 0.46, TOWER_TOP + 46),
                       (cx, TOWER_TOP - 38)], fill=BLUE)


def punch_arches(img):
    """Punch twin pointed-arch holes through each tower using an alpha mask."""
    mask = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(mask)
    for tx in TOWER_XS:
        tw = 66
        for sgn in (-1, 1):
            cx = tx + sgn * tw * 0.5
            aw = tw * 0.33
            ay_top, ay_bot = 320, DECK_Y - 70
            md.rectangle([cx - aw, ay_top + 90, cx + aw, ay_bot], fill=255)
            md.polygon([(cx - aw, ay_top + 92), (cx + aw, ay_top + 92),
                        (cx, ay_top - 60)], fill=255)
    r, g, b, a = img.split()
    keep = Image.eval(mask, lambda v: 255 - v)   # 255 where art survives
    newa = Image.composite(a, Image.new("L", img.size, 0), keep)
    return Image.merge("RGBA", (r, g, b, newa))


def draw_cat(d, cx=512, feet_y=DECK_Y, s=1.18):
    """Cat silhouette mid-stride walking right; paws at deck level."""
    def P(x, y):
        return (cx + x * s, feet_y - y * s)

    def ELL(x0, y0, x1, y1, fill=GREEN):
        a, b = P(x0, y0), P(x1, y1)
        d.ellipse([min(a[0], b[0]), min(a[1], b[1]),
                   max(a[0], b[0]), max(a[1], b[1])], fill=fill)

    def paw(pt, r=8):
        p = P(*pt)
        rr = r * s
        d.ellipse([p[0] - rr, p[1] - rr, p[0] + rr, p[1] + rr], fill=GREEN)

    # torso (level back), chest, haunch
    ELL(-70, 34, 60, 84)
    ELL(-76, 30, -14, 80)
    ELL(14, 28, 82, 82)
    # head with a slight neck blend
    ELL(66, 62, 132, 124)
    ELL(58, 62, 96, 96)
    # ears
    d.polygon([P(76, 110), P(84, 142), P(100, 116)], fill=GREEN)
    d.polygon([P(108, 116), P(122, 140), P(130, 110)], fill=GREEN)
    # muzzle
    ELL(122, 76, 142, 98)

    def leg(pts, w=12):
        pp = [P(*q) for q in pts]
        d.line(pp, fill=GREEN, width=int(w * s), joint="curve")
        paw(pts[-1], r=w * 0.75)

    # walking gait: diagonals opposed; paws touch deck (y=0)
    leg([(48, 46), (58, 22), (66, 0)])          # front near, forward
    leg([(36, 46), (26, 20), (16, 0)])          # front far, trailing
    leg([(-46, 48), (-40, 22), (-30, 0)])       # hind near, under hip
    leg([(-56, 48), (-72, 22), (-88, 0)])       # hind far, extended back

    # tail: long smooth S rising from the haunch
    t = bezier((-72, 62), (-118, 74), (-128, 122), (-96, 150))
    pp = [P(*q) for q in t]
    d.line(pp, fill=GREEN, width=int(12 * s), joint="curve")
    paw((-96, 150), r=7)


def build():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assets = os.path.join(here, "mcabridge", "assets")
    os.makedirs(assets, exist_ok=True)

    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    draw_bridge(d)
    layer = punch_arches(layer)
    d = ImageDraw.Draw(layer)
    # deck slab + railing above it
    d.rectangle([0, DECK_Y, W, DECK_Y + 30], fill=BLUE)
    d.line([(0, DECK_Y - 46), (W, DECK_Y - 46)], fill=BLUE, width=5)
    for x in range(20, W, 64):
        d.line([(x, DECK_Y - 46), (x, DECK_Y)], fill=BLUE, width=3)
    draw_cat(d)

    # neon halo under crisp art
    glow = layer.filter(ImageFilter.GaussianBlur(16))
    glow = glow.point(lambda v: int(v * 0.7))
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(layer)

    # crop transparent margins, pad square so the mark fills the icon
    bbox = out.getbbox()
    if bbox:
        out2 = out.crop(bbox)
        w, h = out2.size
        side = max(w, h) + 90
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        canvas.alpha_composite(out2, ((side - w) // 2, (side - h) // 2))
        out = canvas.resize((1024, 1024), Image.LANCZOS)

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
