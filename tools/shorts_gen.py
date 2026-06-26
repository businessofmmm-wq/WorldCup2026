#!/usr/bin/env python
"""
YouTube Shorts generator for WCPA.
Renders 1080×1920 (9:16) scenes from the latest model snapshots, then assembles
them into an MP4 with ffmpeg (or saves a PNG strip if ffmpeg is absent).

Usage (via run.py):
    python run.py shorts result                     # most recent completed match
    python run.py shorts result --match "Spain|Morocco"
    python run.py shorts daily                      # today's upcoming fixtures
    python run.py shorts odds                       # current title-odds leaderboard

Output:  out/shorts/<mode>_YYYYMMDD_HHMMSS.mp4   (PNG fallback if no ffmpeg)
Deps:    Pillow (in requirements.txt)  +  ffmpeg (winget install ffmpeg)

All content is original: flag images from flagcdn.com (public domain), fonts
Anton + Staatliches (SIL OFL) auto-fetched from Google Fonts on first run.
No FIFA marks, no agency photos, no player likenesses. See ASSETS.md.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Dimensions + paths ────────────────────────────────────────────────────
W, H = 1080, 1920
_ROOT    = Path(__file__).resolve().parent.parent
DIST     = _ROOT / "dist"
FONT_DIR = _ROOT / "viz" / "assets" / "fonts"
OUT      = _ROOT / "out" / "shorts"

# ── Palette (mirrors style.css :root) ─────────────────────────────────────
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
    "Anton-Regular":       "https://github.com/google/fonts/raw/main/ofl/anton/Anton-Regular.ttf",
    "Staatliches-Regular": "https://github.com/google/fonts/raw/main/ofl/staatliches/Staatliches-Regular.ttf",
}


# ── Font helpers (reuse ogcard.py's auto-download pattern) ────────────────
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
               "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf"]:
        if os.path.exists(fb):
            try:
                return ImageFont.truetype(fb, size)
            except Exception:
                pass
    return ImageFont.load_default(size=size)


# ── Drawing primitives ─────────────────────────────────────────────────────
def _pct(v, d=1):
    if v is None:
        return "—"
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
            return fallback
    return fallback


def _load(name: str) -> dict:
    p = DIST / "api" / (name + ".json")
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _base_canvas():
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (W, H), PAPER)
    d   = ImageDraw.Draw(img, "RGBA")
    for xx in range(-H, W, 34):          # diagonal grain
        d.line([(xx, 0), (xx + H, H)], fill=(*INK, 6), width=2)
    for yy in range(0, H, 14):           # halftone dots
        for xi in range(0, W, 14):
            d.ellipse([xi, yy, xi + 2, yy + 2], fill=(*INK, 10))
    return img, d


def _center(d, cx, y, text, font, fill, shadow=None):
    bb = d.textbbox((0, 0), text, font=font)
    x  = cx - (bb[2] - bb[0]) / 2 - bb[0]
    if shadow:
        off, col = shadow
        d.text((x + off, y + off), text, font=font, fill=col)
    d.text((x, y), text, font=font, fill=fill)
    return bb[3] - bb[1]


def _left(d, x, y, text, font, fill):
    d.text((x, y), text, font=font, fill=fill)


def _right(d, rx, y, text, font, fill):
    bb = d.textbbox((0, 0), text, font=font)
    d.text((rx - (bb[2] - bb[0]), y), text, font=font, fill=fill)


def _brand_strip(d, y: int = 40):
    """WCPA badge + tagline across the top of any scene."""
    cx = W // 2
    d.ellipse([cx - 40, y, cx + 40, y + 80], fill=GOLD, outline=EDGE, width=4)
    _center(d, cx, y + 8, "26", _font("Anton-Regular", 50), DARK)
    _center(d, cx, y + 96, "WCPA", _font("Anton-Regular", 60), INK)
    _center(d, cx, y + 166, "WORLD CUP '26  ·  PREDICTION ALBUM",
            _font("Staatliches-Regular", 32), TERRA)


def _cta_strip(d, y: int = H - 160):
    """Bottom call-to-action: wcpa26.com pill + disclaimer."""
    cx = W // 2
    d.rounded_rectangle([60, y, W - 60, y + 90], radius=20, fill=GOLD, outline=EDGE, width=3)
    _center(d, cx, y + 10, "wcpa26.com", _font("Anton-Regular", 56), DARK)
    _center(d, cx, H - 55, "for entertainment only  ·  not betting advice",
            _font("Staatliches-Regular", 28), SOFT)


# ── Scene builders ─────────────────────────────────────────────────────────
def scene_brand():
    """Full cover — shown as the opener in every Short."""
    img, d = _base_canvas()
    cx = W // 2
    d.rectangle([28, 28, W - 28, H - 28], outline=EDGE, width=10)
    d.rectangle([44, 44, W - 44, H - 44], outline=GOLD, width=3)
    d.polygon([(int(W * .55), 0), (int(W * .72), 0),
               (int(W * .45), H), (int(W * .28), H)], fill=(255, 255, 255, 12))
    d.ellipse([cx - 90, 270, cx + 90, 450], fill=GOLD, outline=EDGE, width=8)
    _center(d, cx, 290, "26", _font("Anton-Regular", 110), DARK)
    _center(d, cx, 488, "WORLD CUP", _font("Anton-Regular", 190), INK, shadow=(8, (0, 0, 0, 140)))
    _center(d, cx, 916, "WCPA", _font("Anton-Regular", 100), GOLDDP, shadow=(5, (0, 0, 0, 120)))
    _center(d, cx, 1038, "THE WORLD CUP PREDICTION ALBUM", _font("Staatliches-Regular", 46), INK)
    _center(d, cx, 1110, "USA  ·  CANADA  ·  MEXICO", _font("Staatliches-Regular", 40), TERRA)
    _center(d, cx, H - 200, "wcpa26.com", _font("Staatliches-Regular", 58), GOLD)
    _center(d, cx, H - 128, "for entertainment only  ·  not betting advice",
            _font("Staatliches-Regular", 30), SOFT)
    return img


def scene_result(m: dict):
    """Match result card — score, called/missed stamp, model prediction."""
    img, d = _base_canvas()
    cx = W // 2
    hn  = m.get("home", {}).get("team", "?")
    an  = m.get("away", {}).get("team", "?")
    hs  = m.get("home_score", "-")
    as_ = m.get("away_score", "-")
    called = m.get("called", False)
    fav    = m.get("fav", "?")
    ph, pd, pa = m.get("p_home", 0), m.get("p_draw", 0), m.get("p_away", 0)
    ts = m.get("top_scoreline", "?")

    _brand_strip(d, y=40)

    # section header
    d.rounded_rectangle([60, 256, W - 60, 322], radius=12, fill=CARD, outline=EDGE, width=2)
    _center(d, cx, 262, "MATCH RESULT", _font("Staatliches-Regular", 44), SOFT)

    # team names
    _center(d, W // 4,  348, hn.upper(), _font("Anton-Regular", 54), INK)
    _center(d, cx,      352, "VS",        _font("Staatliches-Regular", 44), SOFT)
    _center(d, 3 * W // 4, 348, an.upper(), _font("Anton-Regular", 54), INK)

    # big score
    _center(d, cx, 440, f"{hs}  –  {as_}", _font("Anton-Regular", 210), INK,
            shadow=(9, (0, 0, 0, 160)))

    # called / missed stamp
    col = GREEN if called else RED
    txt = "✓   MODEL CALLED IT" if called else "✗   MODEL MISSED"
    d.rounded_rectangle([70, 728, W - 70, 836], radius=22, fill=col, outline=EDGE, width=3)
    _center(d, cx, 743, txt, _font("Anton-Regular", 54), INK)

    # model prediction box
    d.rounded_rectangle([50, 876, W - 50, 1210], radius=18, fill=CARD, outline=EDGE, width=2)
    _center(d, cx, 894, "MODEL PREDICTED", _font("Staatliches-Regular", 40), SOFT)
    fav_map = {"home": hn, "draw": "DRAW", "away": an}
    fav_lbl = fav_map.get(fav, "")
    rows = [(hn, _pct(ph, 0)), ("DRAW", _pct(pd, 0)), (an, _pct(pa, 0))]
    for i, (lbl, prob) in enumerate(rows):
        yy = 968 + i * 74
        is_fav = lbl == fav_lbl or (fav == "draw" and lbl == "DRAW")
        f = _font("Anton-Regular" if is_fav else "Staatliches-Regular", 52 if is_fav else 46)
        col2 = GOLDDP if is_fav else SOFT
        _center(d, cx, yy, f"{lbl}  {prob}", f, col2)

    _center(d, cx, 1226, f"LIKELIEST SCORELINE  {ts}",
            _font("Staatliches-Regular", 38), TERRA)
    _cta_strip(d)
    return img


def scene_daily(fixtures: list[dict], record: dict):
    """Today's upcoming match prediction cards."""
    img, d = _base_canvas()
    cx = W // 2
    today = dt.date.today().strftime("%A %d %B %Y").upper()

    _brand_strip(d, y=40)
    _center(d, cx, 280, "TODAY'S PREDICTIONS", _font("Anton-Regular", 70), GOLD,
            shadow=(4, (0, 0, 0, 140)))
    _center(d, cx, 372, today, _font("Staatliches-Regular", 34), TERRA)

    if not fixtures:
        _center(d, cx, H // 2, "NO MATCHES TODAY", _font("Anton-Regular", 60), SOFT)
    else:
        y = 438
        for m in fixtures[:4]:
            hn  = m.get("home", {}).get("team", "?")
            an  = m.get("away", {}).get("team", "?")
            ph  = m.get("p_home", 0)
            pd  = m.get("p_draw", 0)
            pa  = m.get("p_away", 0)
            fav = m.get("fav", "")
            kick = m.get("kickoff", "")
            ktime = ""
            if kick:
                try:
                    ktime = dt.datetime.fromisoformat(kick.replace("Z", "+00:00")).strftime("%H:%M UTC")
                except Exception:
                    ktime = kick[11:16] + " UTC" if len(kick) > 15 else ""

            rh = 294
            d.rounded_rectangle([36, y, W - 36, y + rh], radius=16,
                                 fill=CARD, outline=GOLDDP if fav in ("home","away") else EDGE,
                                 width=3 if fav in ("home","away") else 2)
            _center(d, cx, y + 12, ktime, _font("Staatliches-Regular", 32), SOFT)
            _center(d, W // 4,     y + 52, hn.upper(), _font("Anton-Regular", 50), INK)
            _center(d, cx,         y + 56, "VS",        _font("Staatliches-Regular", 38), SOFT)
            _center(d, 3 * W // 4, y + 52, an.upper(), _font("Anton-Regular", 50), INK)

            # probability bar
            total = ph + pd + pa or 1
            bx, by, bw, bh = 56, y + 128, W - 112, 32
            wh = int(bw * ph / total)
            wd = int(bw * pd / total)
            wa = bw - wh - wd
            d.rounded_rectangle([bx, by, bx + wh, by + bh], radius=7, fill=TEAL)
            d.rectangle([bx + wh, by, bx + wh + wd, by + bh], fill=SOFT)
            d.rounded_rectangle([bx + wh + wd, by, bx + bw, by + bh], radius=7, fill=TERRA)
            f_p = _font("Staatliches-Regular", 30)
            _left(d,  bx + 6,       by + 34, _pct(ph, 0), f_p, INK)
            _center(d, cx,           by + 34, _pct(pd, 0), f_p, INK)
            _right(d, bx + bw - 6,  by + 34, _pct(pa, 0), f_p, INK)

            fav_txt = (hn if fav == "home" else an if fav == "away" else "DRAW").upper()
            _center(d, cx, y + 228, f"MODEL CALLS: {fav_txt}",
                    _font("Anton-Regular", 40), GOLDDP)
            y += rh + 16

        if record and record.get("played"):
            rec_txt = (f"MODEL RECORD: {record['called']}/{record['played']}"
                       f"  ({_pct(record.get('pct'), 0)} correct)")
            _center(d, cx, y + 18, rec_txt, _font("Staatliches-Regular", 34), TEAL)

    _cta_strip(d)
    return img


def scene_odds(title_odds: list[dict], runs: int = 50000):
    """Title odds leaderboard — top 8 nations with conf-coloured bars."""
    img, d = _base_canvas()
    cx = W // 2

    _brand_strip(d, y=40)
    _center(d, cx, 270, "WHO WINS?", _font("Anton-Regular", 126), INK, shadow=(7, (0, 0, 0, 140)))
    _center(d, cx, 416, "2026 FIFA WORLD CUP TITLE ODDS", _font("Staatliches-Regular", 42), GOLD)
    _center(d, cx, 474, f"{runs:,} Monte-Carlo sims  ·  live model",
            _font("Staatliches-Regular", 30), SOFT)

    top = title_odds[:8]
    if not top:
        _center(d, cx, H // 2, "loading...", _font("Staatliches-Regular", 50), SOFT)
        _cta_strip(d)
        return img

    max_p = max(o.get("p_win", 0) for o in top) or 0.01
    medals = ["①", "②", "③", "", "", "", "", ""]
    y = 536
    for i, o in enumerate(top):
        team  = o.get("team", "?")
        p_win = o.get("p_win", 0) or 0
        acc   = _parse_hex(o.get("confed_color"), GOLD)
        bar_w = int((W - 140) * (p_win / max_p))
        rh    = 152
        is_top = i < 3

        d.rounded_rectangle([36, y, W - 36, y + rh - 8], radius=14,
                             fill=CARD, outline=GOLDDP if is_top else EDGE,
                             width=3 if is_top else 2)
        if medals[i]:
            _left(d, 56, y + 38, medals[i], _font("Anton-Regular", 64), GOLDDP)
        tx = 128 if medals[i] else 60
        _left(d, tx, y + 22, team.upper(), _font("Anton-Regular", 58), INK)
        _right(d, W - 52, y + 18, _pct(p_win, 1), _font("Anton-Regular", 68), GOLDDP)
        d.rounded_rectangle([tx, y + 94, tx + bar_w, y + 120], radius=6, fill=acc)
        y += rh

    _cta_strip(d, y=H - 138)
    return img


# ── Video / image assembly ─────────────────────────────────────────────────
def _has_ffmpeg() -> bool:
    try:
        r = subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def render(scenes: list[tuple], out_path: Path) -> str | None:
    """Assemble scenes into an MP4 (ffmpeg) or a PNG strip (fallback)."""
    from PIL import Image
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not _has_ffmpeg():
        strip = Image.new("RGB", (W, H * len(scenes)), PAPER)
        for i, (img, _) in enumerate(scenes):
            strip.paste(img, (0, i * H))
        png = out_path.with_suffix(".png")
        strip.save(str(png), "PNG", optimize=True)
        sz = png.stat().st_size // 1024
        print(f"\n  Saved PNG strip → {png}  ({sz} KB, {len(scenes)} scenes)")
        print("  Tip: install ffmpeg for MP4:  winget install ffmpeg")
        return str(png)

    with tempfile.TemporaryDirectory() as tmp:
        lines: list[str] = []
        for i, (img, dur) in enumerate(scenes):
            fp = os.path.join(tmp, f"s{i:02d}.png")
            img.save(fp, "PNG")
            lines += [f"file '{fp}'\n", f"duration {dur}\n"]
        lines.append(f"file '{os.path.join(tmp, f's{len(scenes)-1:02d}.png')}'\n")
        lst = os.path.join(tmp, "list.txt")
        with open(lst, "w") as f:
            f.writelines(lines)

        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
            "-vf", f"scale={W}:{H}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
            str(out_path),
        ]
        r = subprocess.run(cmd, capture_output=True, timeout=180)
        if r.returncode != 0:
            err = r.stderr.decode(errors="replace")[-500:]
            print(f"  ffmpeg error:\n{err}")
            return None
        sz = out_path.stat().st_size // 1024
        print(f"\n  Saved → {out_path}  ({sz} KB)")
        return str(out_path)


# ── Mode handlers ──────────────────────────────────────────────────────────
def _slug(s: str) -> str:
    return s.lower().replace(" ", "_").replace("/", "-")


def _ts() -> str:
    return dt.datetime.now().strftime("%Y%m%d_%H%M%S")


def make_result(match_key: str | None = None):
    fixtures  = _load("fixtures")
    completed = [m for m in fixtures.get("completed", []) if m.get("home_score") is not None]
    if not completed:
        print("  No completed matches in dist/api/fixtures.json — run export first.")
        return
    if match_key:
        h_q, a_q = (match_key.lower().split("|", 1) + [""])[:2]
        completed = [m for m in completed
                     if h_q in m.get("home", {}).get("team", "").lower()
                     or a_q in m.get("away", {}).get("team", "").lower()]
        if not completed:
            print(f"  No match found for '{match_key}'.")
            return
    m  = completed[-1]
    hn = m.get("home", {}).get("team", "?")
    an = m.get("away", {}).get("team", "?")
    print(f"  Building result Short: {hn} {m.get('home_score')}–{m.get('away_score')} {an}")
    scenes = [(scene_brand(), 3), (scene_result(m), 20)]
    render(scenes, OUT / f"result_{_slug(hn)}_v_{_slug(an)}_{_ts()}.mp4")


def make_daily():
    fixtures  = _load("fixtures")
    today_str = dt.date.today().isoformat()
    upcoming  = [m for m in fixtures.get("upcoming", []) if m.get("date", "")[:10] == today_str]
    if not upcoming:
        all_up = sorted(fixtures.get("upcoming", []), key=lambda m: m.get("kickoff", ""))
        if all_up:
            nd = all_up[0].get("date", "")[:10]
            upcoming = [m for m in all_up if m.get("date", "")[:10] == nd]
    print(f"  Building daily Short: {len(upcoming)} fixture(s)")
    scenes = [(scene_brand(), 3), (scene_daily(upcoming, fixtures.get("record", {})), 25)]
    render(scenes, OUT / f"daily_{_ts()}.mp4")


def make_odds():
    report = _load("report")
    odds   = report.get("title_odds", [])
    runs   = int(report.get("runs", 50000))
    print(f"  Building odds Short: {len(odds)} nations, {runs:,} sims")
    scenes = [(scene_brand(), 3), (scene_odds(odds, runs), 22)]
    render(scenes, OUT / f"odds_{_ts()}.mp4")


# ── CLI ────────────────────────────────────────────────────────────────────
def main(args: list[str]):
    import argparse
    p   = argparse.ArgumentParser(description="WCPA YouTube Shorts generator")
    sub = p.add_subparsers(dest="mode", required=True)

    r = sub.add_parser("result", help="result Short for a completed match")
    r.add_argument("--match", default=None,
                   help='filter match by teams, e.g. "Spain|Morocco"')

    sub.add_parser("daily", help="today\'s upcoming predictions")
    sub.add_parser("odds",  help="title odds leaderboard")

    ns = p.parse_args(args)
    {"result": lambda: make_result(ns.match),
     "daily":  make_daily,
     "odds":   make_odds}[ns.mode]()


if __name__ == "__main__":
    main(sys.argv[1:])
