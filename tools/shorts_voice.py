#!/usr/bin/env python
"""
Voice-over for WCPA YouTube Shorts.

Two responsibilities:
  1. Narration scripts  — turn the same model data the visuals use into spoken
     copy that intertwines the WCPA brand, the live model record, and wcpa26.com.
  2. Synthesis          — render that copy to a WAV with the built-in Windows
     SAPI5 engine (System.Speech) via tools/shorts_tts.ps1. No new pip deps.

The renderer (tools/shorts_gen.py) synthesises the narration first, measures the
WAV length with the stdlib ``wave`` module, sizes the video to cover it, then
muxes the audio in with ffmpeg. If synthesis is unavailable the short renders
silent — same graceful-degradation contract as the rest of the engine.

All copy is original. Disclaimer line mirrors the on-screen card for compliance.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

_HERE   = Path(__file__).resolve().parent
PS1     = _HERE / "shorts_tts.ps1"
BRAND   = "W C P A"                       # spelled so SAPI reads the letters

# Preferred voices, best first. en-GB Hazel gives a calm broadcast read.
_PREFERRED = [
    "Microsoft Hazel Desktop",
    "Microsoft Zira Desktop",
    "Microsoft David Desktop",
    "Microsoft Hazel",
    "Microsoft Zira",
]

_VOICES_CACHE: list[str] | None = None


# ---------------------------------------------------------------------------
# Engine discovery
# ---------------------------------------------------------------------------

def _powershell() -> str | None:
    for name in ("powershell", "pwsh"):
        p = shutil.which(name)
        if p:
            return p
    win = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    return win if os.path.exists(win) else None


def available() -> bool:
    """True when SAPI5 synthesis can plausibly run on this machine."""
    return (sys.platform == "win32"
            and PS1.exists()
            and _powershell() is not None)


def list_voices() -> list[str]:
    """Installed SAPI5 voice names (cached)."""
    global _VOICES_CACHE
    if _VOICES_CACHE is not None:
        return _VOICES_CACHE
    _VOICES_CACHE = []
    ps = _powershell()
    if not ps:
        return _VOICES_CACHE
    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command",
           "Add-Type -AssemblyName System.Speech;"
           "(New-Object System.Speech.Synthesis.SpeechSynthesizer)."
           "GetInstalledVoices()|%{$_.VoiceInfo.Name}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        if r.returncode == 0:
            _VOICES_CACHE = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    except Exception:
        pass
    return _VOICES_CACHE


def pick_voice(prefer: str | None = None) -> str | None:
    """Resolve a usable voice name, honouring an explicit preference."""
    voices = list_voices()
    if prefer:
        for v in voices:
            if prefer.lower() in v.lower():
                return v
        return prefer  # let the PS layer try; it warns + falls back if missing
    for want in _PREFERRED:
        for v in voices:
            if want.lower() == v.lower():
                return v
    return voices[0] if voices else None


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def wav_duration(path: str | Path) -> float:
    try:
        with wave.open(str(path), "rb") as w:
            frames, rate = w.getnframes(), w.getframerate()
            return frames / rate if rate else 0.0
    except Exception:
        return 0.0


def _clean_for_tts(text: str) -> str:
    """Replace glyphs SAPI mispronounces with spoken-friendly equivalents."""
    for bad, good in (("—", ", "), ("–", ", "), ("&", " and "),
                      ("%", " percent"), ("…", ", ")):
        text = text.replace(bad, good)
    while "  " in text:
        text = text.replace("  ", " ")
    return text.replace(" ,", ",").replace(" .", ".").strip()


def synth(text: str, wav_path: str | Path,
          voice: str | None = None, rate: int = -1) -> float | None:
    """
    Render ``text`` to ``wav_path``. Returns the clip duration in seconds,
    or None if synthesis was unavailable or failed (caller falls back to silent).
    """
    if not available() or not text.strip():
        return None
    ps = _powershell()
    wav_path = Path(wav_path)
    wav_path.parent.mkdir(parents=True, exist_ok=True)

    txt = wav_path.with_suffix(".txt")
    txt.write_text(_clean_for_tts(text), encoding="utf-8")
    chosen = pick_voice(voice)

    cmd = [ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PS1),
           "-TextPath", str(txt), "-WavPath", str(wav_path),
           "-Rate", str(int(rate))]
    if chosen:
        cmd += ["-Voice", chosen]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception as exc:
        print(f"  voice-over failed ({exc}); rendering silent")
        return None
    finally:
        try:
            txt.unlink()
        except Exception:
            pass

    if r.returncode != 0 or not wav_path.exists():
        msg = (r.stderr or r.stdout or "unknown error").strip().splitlines()
        print(f"  voice-over failed ({msg[-1] if msg else '?'}); rendering silent")
        return None
    dur = wav_duration(wav_path)
    if dur <= 0:
        return None
    label = chosen or "default voice"
    print(f"  voice-over: {dur:.1f}s narration ({label})")
    return dur


# ---------------------------------------------------------------------------
# Spoken-form helpers
# ---------------------------------------------------------------------------

# Team names SAPI mangles or says too literally.
_TEAM_SAY = {
    "USA": "U S A",
    "IR Iran": "Iran",
    "Korea Republic": "South Korea",
    "Korea DPR": "North Korea",
    "DR Congo": "D R Congo",
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Czechia": "Czech Republic",
    "UAE": "U A E",
}


def _say_team(name: str) -> str:
    return _TEAM_SAY.get(name, name)


def _say_score(h: int, a: int) -> str:
    def w(n: int) -> str:
        return "nil" if n == 0 else str(n)
    if h == a:
        return "nil all" if h == 0 else f"{h} all"
    return f"{w(h)} {w(a)}"


def _say_pct(p: float | None, dp: int = 0) -> str:
    if p is None:
        return "an unknown chance"
    return f"{p * 100:.{dp}f} percent"


def _fav_team(m: dict) -> tuple[str, float]:
    """Return (spoken favourite label, its probability)."""
    fav = m.get("fav", "")
    hn  = _say_team(m.get("home", {}).get("team", "the home side"))
    an  = _say_team(m.get("away", {}).get("team", "the away side"))
    if fav == "home":
        return hn, m.get("p_home", 0) or 0
    if fav == "away":
        return an, m.get("p_away", 0) or 0
    return "a draw", m.get("p_draw", 0) or 0


def _say_kick(kick: str) -> str:
    if not kick:
        return "soon"
    try:
        d = dt.datetime.fromisoformat(kick.replace("Z", "+00:00"))
    except Exception:
        return "soon"
    today = dt.datetime.now(dt.timezone.utc).date()
    delta = (d.date() - today).days
    day = ("today" if delta == 0 else "tomorrow" if delta == 1
           else d.strftime("%A"))
    h12 = d.hour % 12 or 12
    ampm = "a.m." if d.hour < 12 else "p.m."
    when = f"{h12} {ampm}" if d.minute == 0 else f"{h12} {d.minute:02d} {ampm}"
    return f"{day} at {when} U T C"


def _record_line(record: dict | None) -> str | None:
    if not record or not record.get("played"):
        return None
    called = record.get("called", 0)
    played = record.get("played", 0)
    pct    = record.get("pct")
    return (f"For the tournament so far, the model has called {called} of "
            f"{played} results correctly — {_say_pct(pct)}.")


def _join(beats: list[str]) -> str:
    """Join sentence beats into one narration string."""
    return "  ".join(b.strip() for b in beats if b and b.strip())


# ---------------------------------------------------------------------------
# Narration scripts (one per Short mode)
# ---------------------------------------------------------------------------

def script_result(m: dict, record: dict | None = None) -> str:
    hn   = _say_team(m.get("home", {}).get("team", "?"))
    an   = _say_team(m.get("away", {}).get("team", "?"))
    hs   = int(m.get("home_score", 0) or 0)
    as_  = int(m.get("away_score", 0) or 0)
    called = m.get("called", False)
    fav_lbl, fav_p = _fav_team(m)
    top_s = m.get("top_scoreline", "")

    beats = [
        f"Full time at the World Cup. {hn}, {hs}. {an}, {as_}.",
    ]
    if called:
        beats.append(f"The {BRAND} model called it — it made {fav_lbl} "
                     f"the favourite at {_say_pct(fav_p)}.")
    else:
        beats.append(f"An upset. Our model had favoured {fav_lbl} at "
                     f"{_say_pct(fav_p)}, but the game went the other way.")
    if top_s and "-" in top_s:
        ph, pa = top_s.split("-", 1)
        try:
            beats.append("Its single likeliest scoreline was "
                         f"{_say_score(int(ph), int(pa))}.")
        except ValueError:
            pass
    rec = _record_line(record)
    if rec:
        beats.append(rec)
    beats.append("Every match, modelled and graded, at wcpa twenty six dot com. "
                 "For entertainment only — not betting advice.")
    return _join(beats)


def script_daily(fixtures: list, record: dict | None = None) -> str:
    if not fixtures:
        return _join([
            f"No World Cup fixtures on today's card. {BRAND} returns with the "
            "next round of predictions tomorrow.",
            "Full title odds and the prediction album at wcpa twenty six dot com.",
        ])
    n = len(fixtures)
    if n == 1:
        head = f"Today's World Cup card, predicted by {BRAND} — one match to come."
    elif n <= 4:
        head = (f"Today's World Cup card, predicted by {BRAND} — "
                f"{n} matches to come.")
    else:
        head = (f"Today's World Cup card, predicted by {BRAND} — {n} matches to "
                "come. Here are the headline picks.")
    beats = [head]
    for m in fixtures[:4]:
        hn = _say_team(m.get("home", {}).get("team", "?"))
        an = _say_team(m.get("away", {}).get("team", "?"))
        fav_lbl, fav_p = _fav_team(m)
        if m.get("fav") == "draw":
            beats.append(f"{hn} against {an} looks tight — the model sees a "
                         f"draw as the likeliest result at {_say_pct(fav_p)}.")
        else:
            beats.append(f"{hn} against {an}: the model leans {fav_lbl}, "
                         f"{_say_pct(fav_p)}.")
    rec = _record_line(record)
    if rec:
        beats.append(rec)
    beats.append("Full probabilities for every game at wcpa twenty six dot com. "
                 "For entertainment only — not betting advice.")
    return _join(beats)


def script_odds(title_odds: list, runs: int) -> str:
    top = title_odds[:5]
    runs_say = f"{runs:,}"
    beats = [
        f"Who lifts the World Cup? {BRAND} ran {runs_say} Monte Carlo "
        "simulations of the whole tournament.",
    ]
    if top:
        t0 = _say_team(top[0].get("team", "?"))
        p0 = top[0].get("p_win", 0) or 0
        beats.append(f"Leading the field, {t0}, winning {_say_pct(p0, 1)} "
                     "of our simulations.")
        if len(top) > 1:
            t1 = _say_team(top[1].get("team", "?"))
            p1 = top[1].get("p_win", 0) or 0
            beats.append(f"Second, {t1} on {_say_pct(p1, 1)}.")
        if len(top) > 2:
            t2 = _say_team(top[2].get("team", "?"))
            p2 = top[2].get("p_win", 0) or 0
            beats.append(f"Third, {t2}, {_say_pct(p2, 1)}.")
    beats.append("The full title race, re-run after every result, at "
                 "wcpa twenty six dot com. For entertainment only.")
    return _join(beats)


def script_r32(m: dict) -> str:
    hn   = _say_team(m.get("home", {}).get("team", "?"))
    an   = _say_team(m.get("away", {}).get("team", "?"))
    ph   = m.get("p_home", 0) or 0
    pd_v = m.get("p_draw", 0) or 0
    pa   = m.get("p_away", 0) or 0
    fav_lbl, fav_p = _fav_team(m)
    top_s = m.get("top_scoreline", "")
    venue = m.get("venue", "")

    beats = [
        f"Round of thirty two. {hn} against {an}, "
        f"{_say_kick(m.get('kickoff', ''))}.",
    ]
    if venue:
        beats.append(f"Live from {venue}.")
    # Tight three-way if the favourite is under ~45%.
    if fav_p and fav_p < 0.45:
        beats.append(f"The {BRAND} model splits it: {hn}, {_say_pct(ph)}; "
                     f"a draw, {_say_pct(pd_v)}; {an}, {_say_pct(pa)}.")
    else:
        beats.append(f"The {BRAND} model makes {fav_lbl} the pick at "
                     f"{_say_pct(fav_p)}.")
    if top_s and "-" in top_s:
        ph_s, pa_s = top_s.split("-", 1)
        try:
            beats.append("Likeliest scoreline, "
                         f"{_say_score(int(ph_s), int(pa_s))}.")
        except ValueError:
            pass
    beats.append("Our full bracket prediction lives at wcpa twenty six dot com. "
                 "For entertainment only — not betting advice.")
    return _join(beats)
