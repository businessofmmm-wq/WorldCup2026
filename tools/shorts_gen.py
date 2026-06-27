#!/usr/bin/env python
"""
YouTube Shorts generator for WCPA — animated MP4 renderer.
1080x1920 (9:16), 24 fps, libx264, Pillow + ffmpeg.

Usage (via run.py):
    python run.py shorts result [--match "Spain|Morocco"]
    python run.py shorts daily
    python run.py shorts odds
    python run.py shorts r32 [--match "Spain|Morocco"]   # R32 match preview
    python run.py shorts watch [--interval 60]           # live pipeline

Output:  out/shorts/<mode>_YYYYMMDD_HHMMSS.mp4  (PNG strip if no ffmpeg)
Deps:    Pillow (in requirements.txt) + ffmpeg (winget install ffmpeg)

Animation architecture
----------------------
Each scene is a generator yielding (img, duration_s) pairs.
Short durations (1/FPS) = animated frames played at FPS.
Long durations (>1 s)   = static holds in ffmpeg concat demuxer.
Only build-in (~2 s x 24 fps = 48 frames) and fade-out (~12 frames)
are rendered per scene; the static hold is one PNG with a long duration.

All content is original art. See ASSETS.md.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# -- Dimensions & paths ------------------------------------------------------
W, H = 1080, 1920
FPS  = 24
_ROOT    = Path(__file__).resolve().parent.parent
DIST     = _ROOT / "dist"
FONT_DIR = _ROOT / "viz" / "assets" / "fonts"
OUT      = _ROOT / "out" / "shorts"

# -- Palette (mirrors style.css :root) ---------------------------------------
PAPER  = (20,  19,  16)
CARD   = (32,  32,  26)
EDGE   = (56,  51,  43)
INK    = (236, 227, 208)
SOFT   = (169, 156, 131)
GOLD   = (227, 165, 18)
GOLDDP = (212, 154, 22)
TERRA  = (210, 84,  27)
TEAL   = (73,  163, 157)
RED    = (210, 72,  72)
GREEN  = (88,  172, 108)
DARK   = (20,  19,  16)

_FONT_URLS = {
    "Anton-Regular":
        "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "Staatliches-Regular":
        "https://github.com/google/fonts/raw/main/ofl/staatliches/Staatliches-Regular.ttf",
}


# -- Font helpers ------------------------------------------------------------
def _ensure_font(name: str) -> str | None:
    path = FONT_DIR / (name + ".ttf")
    if path.exists():
        return str(path)
    FONT_DIR.mkdir(parents=True, exist_ok=True)
    if name not in _FONT_URLS:
        return None
    try:
        import requests
        r = requests.get(_FONT_URLS[name], timeout=30,
                         headers={"User-Agent": "wcpa-shorts/1.0"})
        r.raise_for_status()
        path.write_bytes(r.content)
        return str(path)
    except Exception as exc:
        print(f"  font {name} unavailable ({exc}); using system fallback")
        return None


def _font(name: str, size: int):
    from PIL import ImageFont
    p = _ensure_font(name)
    if p:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    for fb in [r"C:\Windows\Fonts\impact.ttf", r"C:\Windows\Fonts\arialbd.ttf",
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
               "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
    return ImageFont.load_default(size=size)


# -- Easing & animation math -------------------------------------------------
def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))

def _ease(t: float) -> float:
    """Smoothstep - zero derivative at both ends."""
    t = _clamp(t)
    return t * t * (3 - 2 * t)

def _ease_out(t: float) -> float:
    """Quadratic ease-out."""
    return 1 - (1 - _clamp(t)) ** 2

def _ease_out3(t: float) -> float:
    """Cubic ease-out - snappier."""
    return 1 - (1 - _clamp(t)) ** 3

def _phase(t: float, start: float, end: float) -> float:
    """Normalise global t=0..1 to sub-window [start, end]."""
    if end <= start:
        return 1.0
    return _clamp((t - start) / (end - start))


# -- RGBA canvas & compositing -----------------------------------------------
def _base_canvas():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (W, H), (*PAPER, 255))
    d   = ImageDraw.Draw(img, "RGBA")
    for xx in range(-H, W, 34):
        d.line([(xx, 0), (xx + H, H)], fill=(*INK, 6), width=2)
    for yy in range(0, H, 14):
        for xi in range(0, W, 14):
            d.ellipse([xi, yy, xi + 2, yy + 2], fill=(*INK, 10))
    return img, d


def _to_rgb(img):
    from PIL import Image
    bg = Image.new("RGB", img.size, PAPER)
    bg.paste(img, mask=img.split()[3])
    return bg


def _apply_fade(img, fade: float):
    from PIL import Image
    fade = _clamp(fade)
    if fade >= 1.0:
        return img
    black = Image.new("RGBA", img.size, (0, 0, 0, 255))
    return Image.blend(black, img, fade)


# -- Alpha-aware text helpers ------------------------------------------------
def _tc(img, cx: int, y: int, text: str, font, fill, alpha: int = 255,
        shadow=None):
    """Draw text centred at cx with given alpha."""
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    bb    = ld.textbbox((0, 0), text, font=font)
    x     = cx - (bb[2] - bb[0]) // 2 - bb[0]
    r, g, b = fill[:3]
    if shadow:
        off, sc = shadow
        sr, sg, sb = sc[:3]
        ld.text((x + off, y + off), text, font=font, fill=(sr, sg, sb, alpha // 2))
    ld.text((x, y), text, font=font, fill=(r, g, b, alpha))
    img.alpha_composite(layer)


def _tl(img, x: int, y: int, text: str, font, fill, alpha: int = 255):
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    r, g, b = fill[:3]
    ld.text((x, y), text, font=font, fill=(r, g, b, alpha))
    img.alpha_composite(layer)


def _tr(img, rx: int, y: int, text: str, font, fill, alpha: int = 255):
    from PIL import Image, ImageDraw
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ld    = ImageDraw.Draw(layer)
    bb    = ld.textbbox((0, 0), text, font=font)
    x     = rx - (bb[2] - bb[0])
    r, g, b = fill[:3]
    ld.text((x, y), text, font=font, fill=(r, g, b, alpha))
    img.alpha_composite(layer)


# -- Shared animated UI chrome -----------------------------------------------
def _brand_strip(img, d, y: int = 40, t: float = 1.0):
    """WCPA badge + tagline. t 0->1 animates in."""
    a  = int(255 * _ease_out(t))
    if a <= 0:
        return
    cx = W // 2
    cr = int(40 * _ease_out3(t))
    if cr > 0:
        d.ellipse([cx - cr, y, cx + cr, y + cr * 2],
                  fill=(*GOLD, a), outline=(*EDGE, a), width=4)
    _tc(img, cx, y + 8,   "26",  _font("Anton-Regular", 50),        DARK,  a)
    _tc(img, cx, y + 96,  "WCPA", _font("Anton-Regular", 60),       INK,   a)
    _tc(img, cx, y + 166, "WORLD CUP '26  |  PREDICTION ALBUM",
        _font("Staatliches-Regular", 32), TERRA, a)


def _cta_strip(img, d, y: int = H - 160, t: float = 1.0):
    """wcpa26.com pill + disclaimer. t 0->1 fades in."""
    a  = int(255 * _ease_out(t))
    if a <= 0:
        return
    cx = W // 2
    d.rounded_rectangle([60, y, W - 60, y + 90], radius=20,
                         fill=(*GOLD, a), outline=(*EDGE, a), width=3)
    _tc(img, cx, y + 10, "wcpa26.com", _font("Anton-Regular", 56), DARK, a)
    _tc(img, cx, H - 55, "for entertainment only  |  not betting advice",
        _font("Staatliches-Regular", 28), SOFT, a)


# -- Utility -----------------------------------------------------------------
def _pct(v, d: int = 1) -> str:
    if v is None:
        return "--"
    p = v * 100
    if 0 < p < 0.1:
        return "<0.1%"
    return f"{p:.{d}f}%"


def _parse_hex(color: str | None, fallback=GOLD):
    if not color or not color.startswith("#"):
        return fallback
    s = color.lstrip("#")
    if len(s) == 6:
        try:
            return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
        except ValueError:
            pass
    return fallback


def _load(name: str) -> dict:
    p = DIST / "api" / (name + ".json")
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _slug(s: str) -> str:
    return s.lower().replace(" ", "_").replace("/", "-")


def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def _kick_disp(kick: str, fmt: str = "%d %b %Y  |  %H:%M UTC") -> str:
    if not kick:
        return ""
    try:
        return dt.datetime.fromisoformat(kick.replace("Z", "+00:00")).strftime(fmt)
    except Exception:
        return kick[11:16] + " UTC" if len(kick) > 15 else kick


# ============================================================================
# SCENE: BRAND / INTRO
# ============================================================================

def _brand_frame(t: float, fade: float = 1.0):
    img, d = _base_canvas()
    cx = W // 2

    # border
    a_b = int(255 * _ease_out(_phase(t, 0.0, 0.25)))
    if a_b > 0:
        d.rectangle([28, 28, W - 28, H - 28], outline=(*EDGE, a_b), width=10)
        d.rectangle([44, 44, W - 44, H - 44], outline=(*GOLD, a_b), width=3)

    # diagonal light sweep
    sw = _ease_out3(_phase(t, 0.0, 0.6))
    sx = int(-W * 0.4 + W * 1.8 * sw)
    d.polygon([(sx, 0), (sx + int(W * 0.17), 0),
               (sx + int(W * 0.17) - H, H), (sx - H, H)],
              fill=(255, 255, 255, 10))

    # badge grows
    tb = _ease_out3(_phase(t, 0.1, 0.5))
    ab = int(255 * tb)
    cr = int(90 * tb)
    if cr > 0:
        d.ellipse([cx - cr, 270, cx + cr, 270 + cr * 2],
                  fill=(*GOLD, ab), outline=(*EDGE, ab), width=8)
    _tc(img, cx, 290, "26", _font("Anton-Regular", 110), DARK, ab)

    # "WORLD CUP" slides up
    tm = _ease_out3(_phase(t, 0.25, 0.7))
    am = int(255 * tm)
    sl = int((1 - tm) * 100)
    _tc(img, cx, 488 + sl, "WORLD CUP",
        _font("Anton-Regular", 190), INK, am, shadow=(9, (0, 0, 0)))

    # sub text fades in
    ts = _ease_out(_phase(t, 0.5, 1.0))
    as_ = int(255 * ts)
    _tc(img, cx, 916,  "WCPA",
        _font("Anton-Regular", 100), GOLDDP, as_, shadow=(5, (0, 0, 0)))
    _tc(img, cx, 1038, "THE WORLD CUP PREDICTION ALBUM",
        _font("Staatliches-Regular", 46), INK,   as_)
    _tc(img, cx, 1110, "USA  |  CANADA  |  MEXICO",
        _font("Staatliches-Regular", 40), TERRA, as_)
    _tc(img, cx, H - 200, "wcpa26.com",
        _font("Staatliches-Regular", 58), GOLD, as_)
    _tc(img, cx, H - 128, "for entertainment only  |  not betting advice",
        _font("Staatliches-Regular", 30), SOFT, as_)

    img = _apply_fade(img, fade)
    return _to_rgb(img)


def frames_brand(duration: float = 3.0):
    build = min(1.5, duration * 0.55)
    hold  = max(0.1, duration - build - 0.3)
    n_in  = int(build * FPS)
    n_out = max(6, int(0.3 * FPS))

    for i in range(n_in):
        t      = i / max(n_in - 1, 1)
        fade_in = _ease_out(_phase(t, 0.0, 0.25))
        yield _brand_frame(t, fade=fade_in), 1.0 / FPS

    yield _brand_frame(1.0), hold

    for i in range(n_out):
        fade = 1.0 - _ease(i / max(n_out - 1, 1))
        yield _brand_frame(1.0, fade=fade), 1.0 / FPS


# ============================================================================
# SCENE: MATCH RESULT
# ============================================================================

def _result_frame(m: dict, t: float, fade: float = 1.0):
    img, d = _base_canvas()
    cx = W // 2

    hn     = m.get("home", {}).get("team", "?")
    an     = m.get("away", {}).get("team", "?")
    hs     = m.get("home_score", 0) or 0
    as_    = m.get("away_score", 0) or 0
    called = m.get("called", False)
    fav    = m.get("fav", "?")
    ph, pd, pa = m.get("p_home", 0), m.get("p_draw", 0), m.get("p_away", 0)
    top_s  = m.get("top_scoreline", "?")

    _brand_strip(img, d, y=40, t=_ease_out(_phase(t, 0.0, 0.3)))

    # header
    ah = int(255 * _ease_out(_phase(t, 0.05, 0.35)))
    d.rounded_rectangle([60, 256, W - 60, 322], radius=12,
                         fill=(*CARD, ah), outline=(*EDGE, ah), width=2)
    _tc(img, cx, 262, "MATCH RESULT", _font("Staatliches-Regular", 44), SOFT, ah)

    # team names slide from sides
    tt = _ease_out3(_phase(t, 0.1, 0.45))
    at = int(255 * tt)
    sl = int((1 - tt) * 220)
    _tc(img, W // 4 - sl, 348, hn.upper(), _font("Anton-Regular", 54), INK, at)
    _tc(img, cx,          352, "VS",        _font("Staatliches-Regular", 44), SOFT, at)
    _tc(img, 3*W//4 + sl, 348, an.upper(), _font("Anton-Regular", 54), INK, at)

    # score counts up
    tsc = _ease_out3(_phase(t, 0.3, 0.7))
    asc = int(255 * _ease_out(_phase(t, 0.28, 0.45)))
    _tc(img, cx, 440,
        f"{int(hs * tsc)}  -  {int(as_ * tsc)}",
        _font("Anton-Regular", 210), INK, asc, shadow=(9, (0, 0, 0)))

    # called/missed stamp
    tst = _ease_out3(_phase(t, 0.55, 0.75))
    ast = int(255 * tst)
    col = GREEN if called else RED
    txt = "V  MODEL CALLED IT" if called else "X  MODEL MISSED"
    d.rounded_rectangle([70, 728, W - 70, 836], radius=22,
                         fill=(*col, ast), outline=(*EDGE, ast), width=3)
    _tc(img, cx, 743, txt, _font("Anton-Regular", 54), INK, ast)

    # prediction box
    tp = _ease_out(_phase(t, 0.5, 0.75))
    ap = int(255 * tp)
    d.rounded_rectangle([50, 876, W - 50, 1210], radius=18,
                         fill=(*CARD, ap), outline=(*EDGE, ap), width=2)
    _tc(img, cx, 894, "MODEL PREDICTED", _font("Staatliches-Regular", 40), SOFT, ap)

    # probability rows with mini animated bars
    tbr = _ease_out3(_phase(t, 0.65, 0.95))
    fav_map = {"home": hn, "draw": "DRAW", "away": an}
    fav_lbl = fav_map.get(fav, "")
    for i, (lbl, pval) in enumerate([(hn, ph), ("DRAW", pd), (an, pa)]):
        yy     = 968 + i * 74
        is_fav = (lbl == fav_lbl) or (fav == "draw" and lbl == "DRAW")
        fnt    = _font("Anton-Regular" if is_fav else "Staatliches-Regular",
                        52 if is_fav else 46)
        col2   = GOLDDP if is_fav else SOFT
        bw     = int(180 * (pval or 0) * tbr)
        if bw > 0:
            bx = cx - 90
            d.rounded_rectangle([bx, yy + 50, bx + bw, yy + 64],
                                 radius=4, fill=(*col2, ap))
        _tc(img, cx, yy, f"{lbl}  {_pct(pval, 0)}", fnt, col2, ap)

    tsl = _ease_out(_phase(t, 0.82, 1.0))
    _tc(img, cx, 1228, f"LIKELIEST SCORELINE  {top_s}",
        _font("Staatliches-Regular", 38), TERRA, int(255 * tsl))

    _cta_strip(img, d, t=_ease_out(_phase(t, 0.88, 1.0)))
    img = _apply_fade(img, fade)
    return _to_rgb(img)


def frames_result(m: dict, duration: float = 20.0):
    build = 2.5
    hold  = max(0.1, duration - build - 0.5)
    n_in  = int(build * FPS)
    n_out = max(6, int(0.5 * FPS))

    for i in range(n_in):
        t = i / max(n_in - 1, 1)
        yield _result_frame(m, t), 1.0 / FPS
    yield _result_frame(m, 1.0), hold
    for i in range(n_out):
        yield _result_frame(m, 1.0, fade=1.0 - _ease(i / max(n_out - 1, 1))), 1.0 / FPS


# ============================================================================
# SCENE: DAILY PREDICTIONS
# ============================================================================

def _daily_frame(fixtures: list, record: dict, t: float, fade: float = 1.0):
    img, d = _base_canvas()
    cx     = W // 2
    today  = dt.date.today().strftime("%A %d %B %Y").upper()

    _brand_strip(img, d, y=40, t=_ease_out(_phase(t, 0.0, 0.3)))

    th = _ease_out3(_phase(t, 0.05, 0.38))
    ah = int(255 * th)
    sh = int((1 - th) * 60)
    _tc(img, cx, 280 - sh, "TODAY'S PREDICTIONS",
        _font("Anton-Regular", 70), GOLD, ah)
    _tc(img, cx, 372, today, _font("Staatliches-Regular", 34), TERRA, ah)

    if not fixtures:
        _tc(img, cx, H // 2, "NO MATCHES TODAY",
            _font("Anton-Regular", 60), SOFT, 255)
    else:
        y = 438
        for fi, m in enumerate(fixtures[:4]):
            hn   = m.get("home", {}).get("team", "?")
            an   = m.get("away", {}).get("team", "?")
            ph   = m.get("p_home", 0)
            pd_v = m.get("p_draw", 0)
            pa   = m.get("p_away", 0)
            fav  = m.get("fav", "")
            ktime = _kick_disp(m.get("kickoff", ""), "%H:%M UTC")

            tc = _ease_out3(_phase(t, 0.18 + fi * 0.14, 0.55 + fi * 0.14))
            ac = int(255 * tc)
            sc = int((1 - tc) * 110)
            rh = 294
            is_fav_m = fav in ("home", "away")

            d.rounded_rectangle([36, y + sc, W - 36, y + rh + sc],
                                 radius=16, fill=(*CARD, ac),
                                 outline=(*(GOLDDP if is_fav_m else EDGE), ac),
                                 width=3 if is_fav_m else 2)
            _tc(img, cx,       y + 12 + sc, ktime,  _font("Staatliches-Regular", 32), SOFT, ac)
            _tc(img, W // 4,   y + 52 + sc, hn.upper(), _font("Anton-Regular", 50), INK, ac)
            _tc(img, cx,       y + 56 + sc, "VS",   _font("Staatliches-Regular", 38), SOFT, ac)
            _tc(img, 3*W//4,   y + 52 + sc, an.upper(), _font("Anton-Regular", 50), INK, ac)

            tbr = _ease_out3(_phase(t, 0.36 + fi * 0.14, 0.75 + fi * 0.14))
            total = ph + pd_v + pa or 1
            bx, by, bw, bh = 56, y + 128 + sc, W - 112, 32
            wh = int(bw * ph   / total * tbr)
            wd = int(bw * pd_v / total * tbr)
            wa = int(bw * pa   / total * tbr)
            if wh > 0:
                d.rounded_rectangle([bx, by, bx + wh, by + bh], radius=7,
                                     fill=(*TEAL, ac))
            if wd > 0:
                d.rectangle([bx + wh, by, bx + wh + wd, by + bh], fill=(*SOFT, ac))
            if wa > 0:
                d.rounded_rectangle([bx + wh + wd, by, bx + bw, by + bh], radius=7,
                                     fill=(*TERRA, ac))

            fp = _font("Staatliches-Regular", 30)
            _tl(img,  bx + 6,       by + 34, _pct(ph, 0),   fp, INK, ac)
            _tc(img,  cx,           by + 34, _pct(pd_v, 0), fp, INK, ac)
            _tr(img,  bx + bw - 6, by + 34, _pct(pa, 0),   fp, INK, ac)

            fav_txt = (hn if fav == "home" else an if fav == "away" else "DRAW").upper()
            _tc(img, cx, y + 228 + sc, f"MODEL CALLS: {fav_txt}",
                _font("Anton-Regular", 40), GOLDDP, ac)
            y += rh + 16

        if record and record.get("played"):
            rec = (f"MODEL RECORD: {record['called']}/{record['played']}"
                   f"  ({_pct(record.get('pct'), 0)} correct)")
            tr = _ease_out(_phase(t, 0.88, 1.0))
            _tc(img, cx, y + 18, rec, _font("Staatliches-Regular", 34), TEAL, int(255 * tr))

    _cta_strip(img, d, t=_ease_out(_phase(t, 0.9, 1.0)))
    img = _apply_fade(img, fade)
    return _to_rgb(img)


def frames_daily(fixtures: list, record: dict, duration: float = 25.0):
    build = 3.0
    hold  = max(0.1, duration - build - 0.5)
    n_in  = int(build * FPS)
    n_out = max(6, int(0.5 * FPS))

    for i in range(n_in):
        t = i / max(n_in - 1, 1)
        yield _daily_frame(fixtures, record, t), 1.0 / FPS
    yield _daily_frame(fixtures, record, 1.0), hold
    for i in range(n_out):
        yield _daily_frame(fixtures, record, 1.0,
                           fade=1.0 - _ease(i / max(n_out - 1, 1))), 1.0 / FPS


# ============================================================================
# SCENE: TITLE ODDS LEADERBOARD
# ============================================================================

def _odds_frame(title_odds: list, runs: int, t: float, fade: float = 1.0):
    img, d = _base_canvas()
    cx = W // 2

    _brand_strip(img, d, y=40, t=_ease_out(_phase(t, 0.0, 0.3)))

    th  = _ease_out3(_phase(t, 0.05, 0.42))
    ah  = int(255 * th)
    sz  = int(60 + 66 * th)
    _tc(img, cx, 270, "WHO WINS?", _font("Anton-Regular", sz), INK, ah, shadow=(7, (0, 0, 0)))
    _tc(img, cx, 416, "2026 FIFA WORLD CUP TITLE ODDS",
        _font("Staatliches-Regular", 42), GOLD, ah)
    _tc(img, cx, 474, f"{runs:,} Monte-Carlo sims  |  live model",
        _font("Staatliches-Regular", 30), SOFT, ah)

    top    = title_odds[:8]
    medals = ["1.", "2.", "3.", "", "", "", "", ""]
    if top:
        max_p = max(o.get("p_win", 0) or 0 for o in top) or 0.01
        y = 536
        for i, o in enumerate(top):
            team  = o.get("team", "?")
            p_win = o.get("p_win", 0) or 0
            acc   = _parse_hex(o.get("confed_color"), GOLD)
            rh    = 152
            is_top = i < 3

            tr  = _ease_out3(_phase(t, 0.18 + i * 0.07, 0.52 + i * 0.07))
            ar  = int(255 * tr)
            sl  = int((1 - tr) * 90)

            d.rounded_rectangle([36, y + sl, W - 36, y + rh - 8 + sl],
                                 radius=14, fill=(*CARD, ar),
                                 outline=(*(GOLDDP if is_top else EDGE), ar),
                                 width=3 if is_top else 2)

            tx = 60
            if medals[i]:
                _tl(img, 56, y + 38 + sl, medals[i], _font("Anton-Regular", 64), GOLDDP, ar)
                tx = 128
            _tl(img,  tx,     y + 22 + sl, team.upper(), _font("Anton-Regular", 58), INK,    ar)
            _tr(img,  W - 52, y + 18 + sl, _pct(p_win, 1), _font("Anton-Regular", 68), GOLDDP, ar)

            tbr = _ease_out3(_phase(t, 0.32 + i * 0.07, 0.65 + i * 0.07))
            bw  = int((W - 140) * (p_win / max_p) * tbr)
            if bw > 0:
                d.rounded_rectangle([tx, y + 94 + sl, tx + bw, y + 120 + sl],
                                     radius=6, fill=(*acc, ar))
            y += rh

    _cta_strip(img, d, y=H - 138, t=_ease_out(_phase(t, 0.9, 1.0)))
    img = _apply_fade(img, fade)
    return _to_rgb(img)


def frames_odds(title_odds: list, runs: int, duration: float = 22.0):
    build = 3.5
    hold  = max(0.1, duration - build - 0.5)
    n_in  = int(build * FPS)
    n_out = max(6, int(0.5 * FPS))

    for i in range(n_in):
        t = i / max(n_in - 1, 1)
        yield _odds_frame(title_odds, runs, t), 1.0 / FPS
    yield _odds_frame(title_odds, runs, 1.0), hold
    for i in range(n_out):
        yield _odds_frame(title_odds, runs, 1.0,
                          fade=1.0 - _ease(i / max(n_out - 1, 1))), 1.0 / FPS


# ============================================================================
# SCENE: R32 MATCH PREVIEW  (new)
# ============================================================================

def _r32_frame(m: dict, t: float, fade: float = 1.0):
    img, d = _base_canvas()
    cx = W // 2

    hn    = m.get("home", {}).get("team", "?")
    an    = m.get("away", {}).get("team", "?")
    ph    = m.get("p_home", 0)
    pd_v  = m.get("p_draw", 0)
    pa    = m.get("p_away", 0)
    fav   = m.get("fav", "")
    venue = m.get("venue", "")
    top_s = m.get("top_scoreline", "?")
    kdisp = _kick_disp(m.get("kickoff", ""), "%d %b %Y  |  %H:%M UTC")

    _brand_strip(img, d, y=40, t=_ease_out(_phase(t, 0.0, 0.28)))

    # ROUND OF 32 badge
    tr32 = _ease_out3(_phase(t, 0.04, 0.3))
    ar32 = int(255 * tr32)
    d.rounded_rectangle([180, 256, W - 180, 320], radius=14,
                         fill=(*TERRA, ar32), outline=(*EDGE, ar32), width=2)
    _tc(img, cx, 262, "ROUND OF 32", _font("Anton-Regular", 44), INK, ar32)

    # Home team slides from left
    th = _ease_out3(_phase(t, 0.12, 0.52))
    ah = int(255 * th)
    slh = int((1 - th) * 350)
    _tc(img, W // 4 - slh, 370, hn.upper(), _font("Anton-Regular", 78), INK, ah)

    # Away team slides from right
    ta = _ease_out3(_phase(t, 0.18, 0.58))
    aa = int(255 * ta)
    sla = int((1 - ta) * 350)
    _tc(img, 3 * W // 4 + sla, 370, an.upper(), _font("Anton-Regular", 78), INK, aa)

    # Vertical divider
    td = _ease_out(_phase(t, 0.22, 0.5))
    d.line([(cx, 345), (cx, 1110)], fill=(*EDGE, int(255 * td)), width=4)

    # VS pulsing
    tvs = _ease_out3(_phase(t, 0.3, 0.65))
    avs = int(255 * tvs)
    pulse = 1.0 + 0.04 * math.sin(t * math.pi * 6)
    _tc(img, cx, 770, "VS",
        _font("Anton-Regular", int(200 * pulse)), GOLD, avs, shadow=(8, (0, 0, 0)))

    # Kick-off / venue
    ti = _ease_out(_phase(t, 0.32, 0.58))
    ai = int(255 * ti)
    _tc(img, cx, 1118, kdisp,  _font("Staatliches-Regular", 40), TEAL, ai)
    if venue:
        _tc(img, cx, 1176, venue, _font("Staatliches-Regular", 34), SOFT, ai)

    # 3-way probability bar
    tbr = _ease_out3(_phase(t, 0.5, 0.85))
    abr = int(255 * _ease_out(_phase(t, 0.48, 0.65)))
    total = ph + pd_v + pa or 1
    bx, by, bw, bh = 56, 1270, W - 112, 52
    wh = int(bw * ph   / total * tbr)
    wd = int(bw * pd_v / total * tbr)
    wa = int(bw * pa   / total * tbr)
    if wh > 0:
        d.rounded_rectangle([bx, by, bx + wh, by + bh], radius=10, fill=(*TEAL, abr))
    if wd > 0:
        d.rectangle([bx + wh, by, bx + wh + wd, by + bh], fill=(*SOFT, abr))
    if wa > 0:
        d.rounded_rectangle([bx + wh + wd, by, bx + bw, by + bh], radius=10,
                             fill=(*TERRA, abr))

    fp = _font("Staatliches-Regular", 34)
    _tl(img,  bx + 10,       by + 58, _pct(ph, 0),   fp, TEAL,  abr)
    _tc(img,  cx,             by + 58, _pct(pd_v, 0), fp, SOFT,  abr)
    _tr(img,  bx + bw - 10, by + 58, _pct(pa, 0),   fp, TERRA, abr)

    # Model pick callout
    fav_map = {"home": hn, "draw": "DRAW", "away": an}
    fav_lbl = fav_map.get(fav, "")
    if fav_lbl:
        tp = _ease_out3(_phase(t, 0.74, 0.98))
        ap = int(255 * tp)
        d.rounded_rectangle([56, 1390, W - 56, 1480], radius=20,
                             fill=(*GOLD, ap), outline=(*EDGE, ap), width=3)
        _tc(img, cx, 1403, f"MODEL PICKS: {fav_lbl.upper()}  |  {top_s}",
            _font("Anton-Regular", 46), DARK, ap)

    _cta_strip(img, d, t=_ease_out(_phase(t, 0.86, 1.0)))
    img = _apply_fade(img, fade)
    return _to_rgb(img)


def frames_r32(m: dict, duration: float = 22.0):
    build = 2.5
    hold  = max(0.1, duration - build - 0.5)
    n_in  = int(build * FPS)
    n_out = max(6, int(0.5 * FPS))

    for i in range(n_in):
        t = i / max(n_in - 1, 1)
        yield _r32_frame(m, t), 1.0 / FPS
    yield _r32_frame(m, 1.0), hold
    for i in range(n_out):
        yield _r32_frame(m, 1.0, fade=1.0 - _ease(i / max(n_out - 1, 1))), 1.0 / FPS


# ============================================================================
# VIDEO ASSEMBLY
# ============================================================================

_FF_CACHE: dict[str, str | None] = {}


def _ff_exe(name: str = "ffmpeg") -> str | None:
    """
    Resolve an ffmpeg-family binary even when the shell PATH is stale after a
    fresh `winget install` (the new PATH entry isn't visible until restart).

    Order: WCPA_FFMPEG env (ffmpeg only) -> PATH -> winget Links shim ->
    winget Packages glob (Gyan.FFmpeg).
    """
    if name in _FF_CACHE:
        return _FF_CACHE[name]
    cand: str | None = None
    if name == "ffmpeg":
        env = os.environ.get("WCPA_FFMPEG")
        if env and os.path.exists(env):
            cand = env
    if not cand:
        cand = shutil.which(name)
    if not cand:
        la = os.environ.get("LOCALAPPDATA", "")
        if la:
            link = Path(la) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
            if link.exists():
                cand = str(link)
            else:
                hits = sorted((Path(la) / "Microsoft" / "WinGet" / "Packages")
                              .glob(f"Gyan.FFmpeg*/**/bin/{name}.exe"))
                if hits:
                    cand = str(hits[-1])
    _FF_CACHE[name] = cand
    return cand


def _has_ffmpeg() -> bool:
    return _ff_exe("ffmpeg") is not None


# -- Voice-over config (env-driven so it survives the pipeline's module reloads)
def _voice_cfg() -> tuple[bool, str | None, int]:
    on   = os.environ.get("WCPA_SHORTS_VOICE", "1").lower() not in (
        "0", "false", "no", "off")
    name = os.environ.get("WCPA_SHORTS_VOICE_NAME") or None
    try:
        rate = int(os.environ.get("WCPA_SHORTS_VOICE_RATE", "-1"))
    except ValueError:
        rate = -1
    return on, name, rate


# Silent-mode scene lengths (s) when no narration drives the timing.
_DEFAULT_CONTENT = {"result": 20.0, "daily": 25.0, "odds": 22.0, "r32": 22.0}
_MIN_CONTENT     = {"result": 12.0, "daily": 14.0, "odds": 14.0, "r32": 12.0}
_BRAND_DUR       = 3.0
_VOICE_TAIL      = 0.8   # trailing video held after narration ends


def _voiceover(mode: str, *script_args) -> tuple[str | None, float, float]:
    """
    Build + synthesise narration for a Short, then size the content scene so the
    video covers the audio.  Returns (wav_path|None, content_dur, brand_dur).
    Falls back to silent default timings whenever voice is off or unavailable.
    """
    default = _DEFAULT_CONTENT.get(mode, 22.0)
    on, voice_name, rate = _voice_cfg()
    if not on:
        return None, default, _BRAND_DUR
    try:
        from tools import shorts_voice as sv
    except Exception:
        return None, default, _BRAND_DUR
    if not sv.available():
        print("  voice-over unavailable (no SAPI5); rendering silent")
        return None, default, _BRAND_DUR

    builder = {
        "result": sv.script_result, "daily": sv.script_daily,
        "odds":   sv.script_odds,   "r32":   sv.script_r32,
    }.get(mode)
    if not builder:
        return None, default, _BRAND_DUR
    try:
        script = builder(*script_args)
    except Exception as exc:
        print(f"  narration build failed ({exc}); rendering silent")
        return None, default, _BRAND_DUR
    if not script:
        return None, default, _BRAND_DUR

    OUT.mkdir(parents=True, exist_ok=True)
    wav = OUT / f".vo_{mode}_{_ts()}.wav"
    dur = sv.synth(script, wav, voice=voice_name, rate=rate)
    if not dur:
        return None, default, _BRAND_DUR
    content_dur = max(_MIN_CONTENT.get(mode, 14.0),
                      dur + _VOICE_TAIL - _BRAND_DUR)
    return str(wav), content_dur, _BRAND_DUR


def _cleanup_audio(audio: str | None):
    if not audio:
        return
    try:
        Path(audio).unlink(missing_ok=True)
    except Exception:
        pass


def render(scenes, out_path: Path, audio_path: str | None = None) -> str | None:
    """
    Assemble animated scenes into an MP4 via ffmpeg, or PNG strip fallback.

    scenes      - iterable of generators yielding (PIL.Image, duration_s) pairs.
                  Short duration (1/FPS) => animated frame.
                  Long duration (>1 s)   => static hold (one PNG in concat list).
    audio_path  - optional narration WAV muxed over the video (ignored for the
                  PNG fallback). The video is sized to be >= the audio length.
    """
    from PIL import Image
    OUT.mkdir(parents=True, exist_ok=True)

    all_frames: list[tuple] = []
    print("  Rendering", end="", flush=True)
    for scene in scenes:
        for pair in scene:
            all_frames.append(pair)
            if len(all_frames) % FPS == 0:
                print(".", end="", flush=True)
    print(f" {len(all_frames)} frames", flush=True)

    if not _has_ffmpeg():
        key_frames = [img for img, dur in all_frames if dur > 0.5][:4]
        if not key_frames:
            key_frames = [all_frames[0][0]]
        strip = Image.new("RGB", (W, H * len(key_frames)), PAPER)
        for i, img in enumerate(key_frames):
            strip.paste(img, (0, i * H))
        png = out_path.with_suffix(".png")
        strip.save(str(png), "PNG")
        sz = png.stat().st_size // 1024
        print(f"\n  PNG strip -> {png}  ({sz} KB)")
        print("  Install ffmpeg for MP4:  winget install ffmpeg")
        return str(png)

    ff = _ff_exe("ffmpeg")
    with tempfile.TemporaryDirectory() as tmp:
        lines: list[str] = []
        for i, (img, dur) in enumerate(all_frames):
            fp = os.path.join(tmp, f"f{i:05d}.png")
            img.save(fp, "PNG")
            lines += [f"file '{fp}'\n", f"duration {dur:.6f}\n"]
        lines.append(f"file '{os.path.join(tmp, f'f{len(all_frames)-1:05d}.png')}'\n")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as fh:
            fh.writelines(lines)

        cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", lst]
        has_audio = bool(audio_path and os.path.exists(audio_path))
        if has_audio:
            cmd += ["-i", str(audio_path)]
        cmd += [
            "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ]
        if has_audio:
            cmd += ["-map", "0:v:0", "-map", "1:a:0",
                    "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
        cmd += [str(out_path)]

        result = subprocess.run(cmd, capture_output=True, timeout=300)
        if result.returncode != 0:
            print(f"  ffmpeg error:\n{result.stderr.decode(errors='replace')[-600:]}")
            return None
        sz = out_path.stat().st_size // 1024
        tag = "  (voiced)" if has_audio else ""
        print(f"\n  Saved -> {out_path}  ({sz} KB){tag}")
        return str(out_path)


# ============================================================================
# MODE HANDLERS
# ============================================================================

def make_result(match_key: str | None = None) -> str | None:
    fixtures  = _load("fixtures")
    completed = [m for m in fixtures.get("completed", [])
                 if m.get("home_score") is not None]
    if not completed:
        print("  No completed matches in dist/api/fixtures.json - run export first.")
        return None
    if match_key:
        h_q, a_q = (match_key.lower().split("|", 1) + [""])[:2]
        hits = [m for m in completed
                if h_q in m.get("home", {}).get("team", "").lower()
                or a_q in m.get("away", {}).get("team", "").lower()]
        if not hits:
            print(f"  No match for '{match_key}'.")
            return None
        completed = hits
    m      = completed[-1]
    record = fixtures.get("record", {})
    hn = m.get("home", {}).get("team", "?")
    an = m.get("away", {}).get("team", "?")
    print(f"  Result: {hn} {m.get('home_score')}-{m.get('away_score')} {an}")
    audio, cdur, bdur = _voiceover("result", m, record)
    out = OUT / f"result_{_slug(hn)}_v_{_slug(an)}_{_ts()}.mp4"
    res = render([frames_brand(bdur), frames_result(m, cdur)], out, audio_path=audio)
    _cleanup_audio(audio)
    return res


def make_daily() -> str | None:
    fixtures  = _load("fixtures")
    today_str = dt.date.today().isoformat()
    upcoming  = [m for m in fixtures.get("upcoming", [])
                 if m.get("date", "")[:10] == today_str]
    if not upcoming:
        all_up = sorted(fixtures.get("upcoming", []), key=lambda x: x.get("kickoff", ""))
        if all_up:
            nd       = all_up[0].get("date", "")[:10]
            upcoming = [m for m in all_up if m.get("date", "")[:10] == nd]
    record = fixtures.get("record", {})
    print(f"  Daily: {len(upcoming)} fixture(s)")
    audio, cdur, bdur = _voiceover("daily", upcoming, record)
    out = OUT / f"daily_{_ts()}.mp4"
    res = render([frames_brand(bdur), frames_daily(upcoming, record, cdur)], out,
                 audio_path=audio)
    _cleanup_audio(audio)
    return res


def make_odds() -> str | None:
    report = _load("report")
    odds   = report.get("title_odds", [])
    runs   = int(report.get("runs", 50_000))
    print(f"  Odds: {len(odds)} nations, {runs:,} sims")
    audio, cdur, bdur = _voiceover("odds", odds, runs)
    out = OUT / f"odds_{_ts()}.mp4"
    res = render([frames_brand(bdur), frames_odds(odds, runs, cdur)], out,
                 audio_path=audio)
    _cleanup_audio(audio)
    return res


def make_r32(match_key: str | None = None) -> str | None:
    fixtures = _load("fixtures")
    upcoming = fixtures.get("upcoming", [])
    r32 = [m for m in upcoming
           if "2026-06-28" <= m.get("date", "")[:10] <= "2026-07-04"]
    if not r32:
        r32 = upcoming
    if match_key:
        h_q, a_q = (match_key.lower().split("|", 1) + [""])[:2]
        hits = [m for m in r32
                if h_q in m.get("home", {}).get("team", "").lower()
                or a_q in m.get("away", {}).get("team", "").lower()]
        if not hits:
            print(f"  No R32 match for '{match_key}'.")
            return None
        r32 = hits
    m  = r32[0]
    hn = m.get("home", {}).get("team", "?")
    an = m.get("away", {}).get("team", "?")
    print(f"  R32 preview: {hn} vs {an}")
    audio, cdur, bdur = _voiceover("r32", m)
    out = OUT / f"r32_{_slug(hn)}_v_{_slug(an)}_{_ts()}.mp4"
    res = render([frames_brand(bdur), frames_r32(m, cdur)], out, audio_path=audio)
    _cleanup_audio(audio)
    return res


# ============================================================================
# CLI
# ============================================================================

def _add_voice_args(sp):
    sp.add_argument("--no-voice", dest="voice", action="store_false",
                    help="render silent (skip narration)")
    sp.add_argument("--voice-name", default=None,
                    help='SAPI5 voice substring, e.g. "Zira", "David", "Hazel"')
    sp.add_argument("--rate", type=int, default=None,
                    help="speech rate, -10 (slow) .. 10 (fast); default -1")
    sp.set_defaults(voice=True)


def _apply_voice_env(ns):
    if getattr(ns, "voice", True) is False:
        os.environ["WCPA_SHORTS_VOICE"] = "0"
    if getattr(ns, "voice_name", None):
        os.environ["WCPA_SHORTS_VOICE_NAME"] = ns.voice_name
    if getattr(ns, "rate", None) is not None:
        os.environ["WCPA_SHORTS_VOICE_RATE"] = str(ns.rate)


def main(args: list[str]):
    import argparse
    p   = argparse.ArgumentParser(description="WCPA YouTube Shorts generator")
    sub = p.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("result", help="result Short for a completed match")
    r.add_argument("--match", default=None, help='teams e.g. "Spain|Morocco"')
    _add_voice_args(r)

    d = sub.add_parser("daily", help="today predictions Short")
    _add_voice_args(d)
    o = sub.add_parser("odds",  help="title-odds leaderboard Short")
    _add_voice_args(o)

    r32 = sub.add_parser("r32", help="R32 match preview Short")
    r32.add_argument("--match", default=None, help='teams e.g. "Germany|Sweden"')
    _add_voice_args(r32)

    ns = p.parse_args(args)
    _apply_voice_env(ns)
    {
        "result": lambda: make_result(getattr(ns, "match", None)),
        "daily":  make_daily,
        "odds":   make_odds,
        "r32":    lambda: make_r32(getattr(ns, "match", None)),
    }[ns.mode]()


if __name__ == "__main__":
    main(sys.argv[1:])
