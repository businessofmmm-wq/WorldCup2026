"""
API-Football (v3, api-sports.io) — live players & tactics layer.

The free feeds (football-data, sportsdb) give scores only. API-Football adds the
"players / tactics" data the model otherwise can't see: squads, **injuries**,
**line-ups + formations**, and team statistics for the current World Cup.

This module is a thin, robust client + a couple of derived helpers. It does NOT
silently alter predictions — wiring an availability signal into the model is a
separate, backtest-gated step (see tools/backtest_agent.py and config.FORM_*).
Today it (a) exposes the data and (b) computes a conservative per-team
`availability` index you can fold into the form overlay once validated.

Auth: free key from https://dashboard.api-football.com (api-sports.io). Put it in
.env as APIFOOTBALL_KEY=...  (copy from Session1.txt). Never hard-code it.

Rate limits (free tier): ~10 req/min, ~100 req/day — so results are cached and the
helpers fetch sparingly. Every call is best-effort and never raises fatally.
"""
from __future__ import annotations
import os
import time
from typing import Optional

import requests

try:
    import config
except Exception:  # importable even outside the app
    config = None

_BASE = os.environ.get("APIFOOTBALL_BASE", "https://v3.football.api-sports.io")
_KEY = (os.environ.get("APIFOOTBALL_KEY") or os.environ.get("WCPA_APIFOOTBALL_KEY")
        or (getattr(config, "APIFOOTBALL_KEY", "") if config else "") or "").strip()
# API-Football league id for the FIFA World Cup is 1; current edition season = 2026.
_LEAGUE = int(os.environ.get("APIFOOTBALL_LEAGUE", "1"))
_SEASON = int(os.environ.get("APIFOOTBALL_SEASON", "2026"))

_CACHE: dict = {}
_TTL = 600.0
_BLOCKED = False   # set True once the API reports a plan/season block — stop wasting quota


def configured() -> bool:
    return bool(_KEY)


def _hdrs() -> dict:
    # api-sports.io uses x-apisports-key; the RapidAPI gateway uses x-rapidapi-key.
    if "rapidapi" in _BASE:
        return {"x-rapidapi-key": _KEY, "x-rapidapi-host": _BASE.split("//")[-1]}
    return {"x-apisports-key": _KEY}


def _get(path: str, params: dict | None = None) -> list:
    """GET an endpoint, return its `response` list. Cached; never raises."""
    global _BLOCKED
    if not _KEY or _BLOCKED:
        return []
    ckey = path + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
    hit = _CACHE.get(ckey)
    if hit and time.time() - hit[0] < _TTL:
        return hit[1]
    try:
        r = requests.get(f"{_BASE.rstrip('/')}/{path.lstrip('/')}",
                         headers=_hdrs(), params=params or {}, timeout=25)
        r.raise_for_status()
        data = r.json() or {}
        resp = data.get("response") or []
        errs = data.get("errors")
        if errs:
            print(f"  api-football {path} errors: {errs}")
            if "plan" in str(errs).lower() or "season" in str(errs).lower():
                _BLOCKED = True
                print("  api-football: free plan lacks this season (2022-2024 only) — "
                      "players/tactics layer disabled this run; upgrade the plan or set "
                      "APIFOOTBALL_SEASON to a covered season for testing.")
        _CACHE[ckey] = (time.time(), resp)
        return resp
    except Exception as exc:
        print(f"  api-football {path} failed: {exc}")
        return []


# --------------------------------------------------------------------------- #
# Raw endpoints
# --------------------------------------------------------------------------- #
def fixtures(league: int = _LEAGUE, season: int = _SEASON) -> list:
    return _get("fixtures", {"league": league, "season": season})


def lineups(fixture_id: int) -> list:
    """Formations + starting XI + bench + coach for one fixture."""
    return _get("fixtures/lineups", {"fixture": fixture_id})


def injuries(team_id: int | None = None, league: int = _LEAGUE, season: int = _SEASON) -> list:
    params = {"league": league, "season": season}
    if team_id:
        params = {"team": team_id, "season": season}
    return _get("injuries", params)


def team_id_for(name: str) -> Optional[int]:
    """Resolve a national-team name to its API-Football team id (cached search)."""
    if not name:
        return None
    resp = _get("teams", {"search": name})
    for row in resp:
        t = row.get("team") or {}
        if t.get("national") and t.get("id"):
            return t["id"]
    if resp:
        return (resp[0].get("team") or {}).get("id")
    return None


# --------------------------------------------------------------------------- #
# Derived signal — conservative, documented, NOT auto-applied to predictions.
# --------------------------------------------------------------------------- #
def team_availability(team_name: str) -> dict:
    """A 0..1 availability index from current injuries (1.0 = full squad).
    Heuristic: each listed injury trims availability a little, floored at 0.6 so a
    long injury list can't, on its own, swing a prediction. Returns the raw list too
    so a future (validated) integration can weight by player importance."""
    tid = team_id_for(team_name)
    inj = injuries(team_id=tid) if tid else []
    out = [{"player": (i.get("player") or {}).get("name"),
            "type": (i.get("player") or {}).get("type") or i.get("type"),
            "reason": (i.get("player") or {}).get("reason")} for i in inj]
    idx = max(0.6, 1.0 - 0.03 * len(out))
    return {"team": team_name, "team_id": tid, "n_injuries": len(out),
            "availability": round(idx, 3), "injuries": out}


def ingest(verbose: bool = True) -> dict:
    """Connectivity / freshness check — fetch this season's WC fixtures + injuries
    and report counts. Safe to call from a pipeline; stores nothing (no schema
    change). Returns a small summary dict."""
    if not _KEY:
        if verbose:
            print("  APIFOOTBALL_KEY not set — skipping players/tactics layer")
        return {"configured": False}
    fx = fixtures()
    inj = injuries()
    if verbose:
        print(f"  api-football: {len(fx)} WC fixtures, {len(inj)} injury records (season {_SEASON})")
    return {"configured": True, "fixtures": len(fx), "injuries": len(inj)}


if __name__ == "__main__":
    print("configured:", configured(), "| base:", _BASE, "| league:", _LEAGUE, "season:", _SEASON)
    print(ingest())
    for t in ("Spain", "Germany", "Brazil"):
        a = team_availability(t)
        print(f"  {t:<10} id={a['team_id']} injuries={a['n_injuries']} avail={a['availability']}")
