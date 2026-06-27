#!/usr/bin/env python
"""
WCPA YouTube Shorts live production pipeline.
Watches dist/api/fixtures.json and auto-generates Shorts when:
  1. A new completed match appears     → make_result()
  2. First run of a new calendar day   → make_daily()
  3. A fresh export is detected        → make_odds()  (rate-limited)

State is persisted in out/shorts/.pipeline_state.json so restarts
don't re-fire old events.

Run (via run.py):
    python run.py shorts watch               # loop every 60 s
    python run.py shorts watch --interval 30
    python run.py shorts watch --once        # one scan then exit
    python run.py shorts watch --auto-open   # open each MP4 after render

Kill with Ctrl-C.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT      = Path(__file__).resolve().parent.parent
DIST       = _ROOT / "dist"
OUT        = _ROOT / "out" / "shorts"
STATE_FILE = OUT / ".pipeline_state.json"
LOG_FILE   = OUT / "pipeline.log"

DEFAULT_INTERVAL = 60    # seconds between polls
DAILY_HOUR       = 6     # UTC hour at which daily short fires (0–23)
ODDS_COOLDOWN    = 3600  # min seconds between odds shorts


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _log(msg: str):
    ts = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        OUT.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "seen_match_ids":    [],
        "last_daily_date":   "",
        "last_odds_ts":      0,
        "last_fixtures_mtime": 0.0,
    }


def _save_state(state: dict):
    OUT.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _fixtures_mtime() -> float:
    p = DIST / "api" / "fixtures.json"
    return p.stat().st_mtime if p.exists() else 0.0


def _load_fixtures() -> dict:
    p = DIST / "api" / "fixtures.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _match_id(m: dict) -> str:
    h = m.get("home", {}).get("team", "?")
    a = m.get("away", {}).get("team", "?")
    d = m.get("date", "")[:10]
    return f"{d}|{h}|{a}"


# ---------------------------------------------------------------------------
# Auto-open helpers
# ---------------------------------------------------------------------------

def _open_file(path: str | None):
    if not path:
        return
    try:
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception as exc:
        _log(f"  auto-open failed: {exc}")


# ---------------------------------------------------------------------------
# Inline imports of shorts_gen modes (avoids re-importing at module level)
# ---------------------------------------------------------------------------

def _gen():
    """Lazy-import tools/shorts_gen.py modes."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "shorts_gen",
        Path(__file__).parent / "shorts_gen.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Single scan pass
# ---------------------------------------------------------------------------

def scan(state: dict, auto_open: bool = False) -> dict:
    fixtures   = _load_fixtures()
    now_utc    = dt.datetime.utcnow()
    now_ts     = time.time()
    today_str  = now_utc.date().isoformat()
    cur_mtime  = _fixtures_mtime()
    changed    = False

    gen = None  # lazy-load only if we need to render

    # 1. New completed matches → result short
    completed = [m for m in fixtures.get("completed", [])
                 if m.get("home_score") is not None]
    seen = set(state.get("seen_match_ids", []))
    new_matches = [m for m in completed if _match_id(m) not in seen]

    for m in new_matches:
        mid = _match_id(m)
        hn  = m.get("home", {}).get("team", "?")
        an  = m.get("away", {}).get("team", "?")
        _log(f"New result: {hn} {m.get('home_score')}-{m.get('away_score')} {an}  → result short")
        try:
            gen = gen or _gen()
            path = gen.make_result(f"{hn}|{an}")
            if path:
                _log(f"  ✓ saved {path}")
                if auto_open:
                    _open_file(path)
        except Exception as exc:
            _log(f"  ✗ result short failed: {exc}")
        seen.add(mid)
        changed = True

    state["seen_match_ids"] = sorted(seen)

    # 2. Daily short (once per day, at or after DAILY_HOUR UTC)
    last_daily = state.get("last_daily_date", "")
    if today_str != last_daily and now_utc.hour >= DAILY_HOUR:
        _log(f"Daily trigger ({today_str}) → daily short")
        try:
            gen = gen or _gen()
            path = gen.make_daily()
            if path:
                _log(f"  ✓ saved {path}")
                if auto_open:
                    _open_file(path)
        except Exception as exc:
            _log(f"  ✗ daily short failed: {exc}")
        state["last_daily_date"] = today_str
        changed = True

    # 3. Export detected → odds short (rate-limited)
    last_mtime = state.get("last_fixtures_mtime", 0.0)
    last_odds  = state.get("last_odds_ts", 0)
    if (cur_mtime > last_mtime and last_mtime > 0
            and (now_ts - last_odds) >= ODDS_COOLDOWN):
        _log(f"Export detected (mtime changed) → odds short")
        try:
            gen = gen or _gen()
            path = gen.make_odds()
            if path:
                _log(f"  ✓ saved {path}")
                if auto_open:
                    _open_file(path)
        except Exception as exc:
            _log(f"  ✗ odds short failed: {exc}")
        state["last_odds_ts"] = int(now_ts)
        changed = True

    state["last_fixtures_mtime"] = cur_mtime

    if changed:
        _save_state(state)

    return state


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------

def watch(interval: int = DEFAULT_INTERVAL,
          auto_open: bool = False,
          once: bool = False):
    OUT.mkdir(parents=True, exist_ok=True)
    state = _load_state()
    _log(f"Pipeline started  interval={interval}s  auto_open={auto_open}  once={once}")
    _log(f"State: {STATE_FILE}")
    _log(f"Log:   {LOG_FILE}")

    try:
        while True:
            state = scan(state, auto_open=auto_open)
            if once:
                _log("--once: exiting after single scan")
                break
            _log(f"Sleeping {interval}s …")
            time.sleep(interval)
    except KeyboardInterrupt:
        _log("Pipeline stopped (Ctrl-C)")


# ---------------------------------------------------------------------------
# CLI (called directly or via run.py)
# ---------------------------------------------------------------------------

def main(args: list[str]):
    import argparse
    p = argparse.ArgumentParser(description="WCPA Shorts live pipeline")
    p.add_argument("--interval",  type=int,  default=DEFAULT_INTERVAL,
                   help="poll interval in seconds (default 60)")
    p.add_argument("--auto-open", action="store_true",
                   help="open each generated MP4 in the default player")
    p.add_argument("--once",      action="store_true",
                   help="run one scan then exit (useful for cron)")
    p.add_argument("--no-voice", dest="voice", action="store_false",
                   help="render silent (skip the SAPI5 narration)")
    p.add_argument("--voice-name", default=None,
                   help='SAPI5 voice substring, e.g. "Zira", "David", "Hazel"')
    p.add_argument("--rate", type=int, default=None,
                   help="speech rate, -10 (slow) .. 10 (fast); default -1")
    p.set_defaults(voice=True)
    ns = p.parse_args(args)

    # Voice config travels via env so it survives the per-scan module reloads
    # in _gen() (importlib creates a fresh shorts_gen each time).
    if ns.voice is False:
        os.environ["WCPA_SHORTS_VOICE"] = "0"
    if ns.voice_name:
        os.environ["WCPA_SHORTS_VOICE_NAME"] = ns.voice_name
    if ns.rate is not None:
        os.environ["WCPA_SHORTS_VOICE_RATE"] = str(ns.rate)

    watch(interval=ns.interval, auto_open=ns.auto_open, once=ns.once)


if __name__ == "__main__":
    main(sys.argv[1:])
