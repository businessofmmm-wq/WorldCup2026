#!/usr/bin/env python
"""Original OG / share-card generator for WCPA (build-time, Pillow).

    python run.py ogcard            -> viz/static/og-cover.png  (1200x630)

100% original art — paper, halftone, foil, type — with NO FIFA / Panini / agency /
player assets (see ASSETS.md). Display type is Anton (SIL OFL); the TTF is fetched and
cached into viz/assets/fonts/ on first run so the card renders the same on any machine.
Pillow is a build-time-only dependency; the static site and live server never import it.
"""
from __future__ import annotations
import os
import sys

W, H = 1200, 630
HERE = os.path.dirname(os.path.abspath(__file__))
FONT_DIR = os.path.join(HERE, "assets", "fonts")
STATIC = os.path.join(HERE, "static")

# palette — mirrors viz/static/style.css :root (dark "collector's album" theme)
PAPER  = (20, 19, 16)        # --bg     #141310
EDGE   = (56, 51, 43)        # --card-edge #38332b
INK    = (236, 227, 208)     # --ink    #ece3d0  (light type on dark)
DARK   = (20, 19, 16)        # type that sits ON a gold/accent fill
SOFT   = (169, 156, 131)     # --ink-soft #a99c83
GOLD   = (227, 165, 18)
GOLDDP = (212, 154, 22)      # brightened for contrast on the dark card
TERRA  = (210, 84, 27)

# name -> Google Fonts OFL raw TTF
FONTS = {
    "Anton-Regular": "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "Staatliches-Regular": "https://github.com/google/fonts/raw/main/ofl/staatliches/Staatliches-Regular.ttf",
}


def _ensure_font(name: str):
    path = os.path.join(FONT_DIR, name + ".ttf")
    if os.path.exists(path):
        return path
    os.makedirs(FONT_DIR, exist_ok=True)
    try:
        import requests
        r = requests.get(FONTS[name], timeout=30,
                         headers={"User-Agent": "wcpa-ogcard/1.0"})
        r.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(r.content)
        note = os.path.join(FONT_DIR, "README.txt")
        if not os.path.exists(note):
            with open(note, "w", encoding="utf-8") as fh:
                fh.write("Fonts here are SIL Open Font License 1.1 (Google Fonts) — free "
                         "for commercial use & embedding.\nAnton, Staatliches. Fetched by "
                         "viz/ogcard.py for build-time share-card rendering.\n")
        return path
    except Exception as exc:
        print(f"  (font {name} unavailable: {exc}; falling back)")
        return None


def _font(name: str, size: int):
    from PIL import ImageFont
    path = _ensure_font(name)
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    for fb in (r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf"):
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
    return ImageFont.load_default()


def _center(d, cx, y, text, font, fill, shadow=None):
    b = d.textbbox((0, 0), text, font=font)
    x = cx - (b[2] - b[0]) / 2 - b[0]
    if shadow:
        off, col = shadow
        d.text((x + off, y + off), text, font=font, fill=col)
    d.text((x, y), text, font=font, fill=fill)


def build(out: str | None = None) -> str:
    from PIL import Image, ImageDraw
    out = out or os.path.join(STATIC, "og-cover.png")
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img, "RGBA")

    # dark card surface: faint light hatch + halftone dots (grain, not noise)
    for x in range(-H, W, 26):
        d.line([(x, 0), (x + H, H)], fill=(236, 227, 208, 7), width=2)
    for yy in range(0, H, 12):
        for xx in range(0, W, 12):
            d.ellipse([xx, yy, xx + 2, yy + 2], fill=(236, 227, 208, 10))

    # sticker frame
    d.rectangle([18, 18, W - 18, H - 18], outline=EDGE, width=8)
    d.rectangle([30, 30, W - 30, H - 30], outline=GOLD, width=3)

    # foil sheen — translucent diagonal band under the type
    d.polygon([(int(W * 0.56), 0), (int(W * 0.72), 0),
               (int(W * 0.42), H), (int(W * 0.26), H)], fill=(255, 255, 255, 14))

    # gold "26" ball badge
    cx, cy, r = W // 2, 110, 46
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GOLD, outline=EDGE, width=5)
    d.ellipse([cx - r + 8, cy - r + 8, cx + r - 8, cy + r - 8],
              outline=(250, 244, 226, 130), width=2)
    _center(d, cx, cy - 30, "26", _font("Anton-Regular", 44), DARK)

    _center(d, cx, 176, "USA  ·  CANADA  ·  MEXICO  ·  48 TEAMS  ·  104 MATCHES",
            _font("Staatliches-Regular", 27), TERRA)
    _center(d, cx, 212, "WORLD CUP", _font("Anton-Regular", 138), INK,
            shadow=(5, (0, 0, 0, 140)))
    _center(d, cx, 372, "WCPA  ’26", _font("Anton-Regular", 84), GOLDDP,
            shadow=(4, (0, 0, 0, 120)))
    _center(d, cx, 478, "THE WORLD CUP PREDICTION ALBUM",
            _font("Staatliches-Regular", 34), INK)
    _center(d, cx, 548, "wcpa26.com  ·  a prediction album, not betting advice",
            _font("Staatliches-Regular", 24), SOFT)

    img.save(out, "PNG")
    print(f"  wrote {out}  ({os.path.getsize(out) // 1024} KB, {W}x{H})")
    return out


def main(args):
    out = args[0] if args and not args[0].startswith("-") else None
    build(out)


if __name__ == "__main__":
    main(sys.argv[1:])
