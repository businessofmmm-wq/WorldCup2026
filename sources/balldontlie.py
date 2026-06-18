"""
BALLDONTLIE FIFA API — match stats (xG, shots) for the World Cup.

BALLDONTLIE's FIFA API covers the 2026 tournament on the free/trial key and
exposes per-match team stats incl. expected goals. This module backfills
matches.home_xg / matches.away_xg for finished WC2026 games.

Conventions (from docs.balldontlie.io): base https://api.balldontlie.io/fifa/v1,
header `Authorization: <KEY>` (raw key, no Bearer), cursor pagination
(?cursor=&per_page=100), payload in `data[]`, `meta.next_cursor`.

Auth: put BALLDONTLIE_KEY in .env. Free/trial = 5 req/min, so this paces itself.

The FIFA stat field/endpoint names aren't pinned here (couldn't reach the FIFA
docs from the build sandbox), so xG extraction is schema-robust: it recursively
finds the expected-goals value per team and maps it home/away by team id, trying
a few endpoint shapes. If nothing matches, run `python -m sources.balldontlie --probe`
to dump one game's raw JSON and tell me the real field names — I'll pin them.

Run:  python -m sources.balldontlie            # backfill xG
      python -m sources.balldontlie --probe    # dump a sample game's schema
"""
from __future__ import annotations
import os
import sys
import json
import time
import datetime as dt

import requests

from db import connect
from sources import sportsdb as _sportsdb

_BASE = os.environ.get("BALLDONTLIE_BASE", "https://api.balldontlie.io/fifa/v1")
_KEY = (os.environ.get("BALLDONTLIE_KEY") or os.environ.get("BALLDONTLIE_API_KEY") or "").strip()
_SEASON = int(os.environ.get("BALLDONTLIE_SEASON", "2026"))
_PACE = float(os.environ.get("BALLDONTLIE_PACE", "13"))   # seconds between calls (free=5/min)

# BALLDONTLIE country names -> our canonical (martj42) names, where they differ.
_BDL_NAME = {
    "USA": "United States", "Korea Republic": "South Korea", "South Korea": "South Korea",
    "Czechia": "Czech Republic", "Cape Verde Islands": "Cape Verde", "IR Iran": "Iran",
    "Côte d'Ivoire": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast", "Türkiye": "Turkey",
    "Turkiye": "Turkey", "Curacao": "Curaçao", "DR Congo": "DR Congo", "Congo DR": "DR Congo",
}


def configured() -> bool:
    return bool(_KEY)


def _canon(name: str) -> str:
    return _sportsdb._canon(_BDL_NAME.get((name or "").strip(), name))


def _get(path: str, params: dict | None = None) -> dict:
    if not _KEY:
        return {}
    try:
        r = requests.get(f"{_BASE.rstrip('/')}/{path.lstrip('/')}",
                         headers={"Authorization": _KEY}, params=params or {}, timeout=25)
        if r.status_code == 429:
            time.sleep(_PACE); r = requests.get(
                f"{_BASE.rstrip('/')}/{path.lstrip('/')}",
                headers={"Authorization": _KEY}, params=params or {}, timeout=25)
        r.raise_for_status()
        return r.json() or {}
    except Exception as exc:
        print(f"  balldontlie {path} failed: {exc}")
        return {}


def _paged(path: str, params: dict | None = None, cap: int = 500) -> list:
    """Follow cursor pagination, return all `data` rows (capped)."""
    out, cur, p = [], None, dict(params or {}); p.setdefault("per_page", 100)
    while len(out) < cap:
        if cur:
            p["cursor"] = cur
        d = _get(path, p)
        rows = d.get("data") or []
        out.extend(rows)
        cur = (d.get("meta") or {}).get("next_cursor")
        if not cur or not rows:
            break
        time.sleep(_PACE)
    return out


def games(season: int = _SEASON) -> list[dict]:
    return _paged("games", {"seasons[]": season})


def _team_names(g: dict):
    """Pull (home_name, away_name, home_id, away_id) from a game row, shape-tolerant."""
    ht = g.get("home_team") or g.get("homeTeam") or {}
    at = g.get("away_team") or g.get("awayTeam") or {}
    return (ht.get("name") or ht.get("full_name"), at.get("name") or at.get("full_name"),
            ht.get("id"), at.get("id"))


def find_game(home: str, away: str, date: dt.date, cache: list | None = None) -> dict | None:
    gs = cache if cache is not None else games()
    h, a = _canon(home).lower(), _canon(away).lower()
    for g in gs:
        hn, an, *_ = _team_names(g)
        gd = str(g.get("date") or g.get("datetime") or "")[:10]
        try:
            ok_date = abs((dt.date.fromisoformat(gd) - date).days) <= 1 if gd else True
        except Exception:
            ok_date = True
        if ok_date and _canon(hn).lower() == h and _canon(an).lower() == a:
            return g
    return None


def _find_xg(obj):
    """Recursively find an expected-goals number anywhere in a stat object."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if ("xg" == kl or "expected_goal" in kl or "expected goals" in kl) and isinstance(v, (int, float, str)):
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        for v in obj.values():
            r = _find_xg(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_xg(v)
            if r is not None:
                return r
    return None


def game_xg(g: dict) -> tuple | None:
    """Return (home_xg, away_xg) for a game, trying inline fields then stat endpoints."""
    hn, an, hid, aid = _team_names(g)
    gid = g.get("id")
    # (a) inline on the game object
    hx = _find_xg({k: v for k, v in g.items() if "home" in str(k).lower()})
    ax = _find_xg({k: v for k, v in g.items() if "away" in str(k).lower()})
    if hx is not None and ax is not None:
        return hx, ax
    # (b) per-game team-stats endpoints (names vary across BDL sports)
    for path in ("game_team_stats", "team_game_stats", f"games/{gid}/team_stats"):
        rows = _paged(path, {"game_ids[]": gid}) if "games/" not in path else (_get(path).get("data") or [])
        if not rows:
            continue
        by = {}
        for row in rows:
            tid = ((row.get("team") or {}).get("id")) or row.get("team_id")
            x = _find_xg(row)
            if tid is not None and x is not None:
                by[tid] = x
        if hid in by and aid in by:
            return by[hid], by[aid]
        if len(by) == 2:                      # fall back to order if ids don't line up
            vals = list(by.values()); return vals[0], vals[1]
    return None


def ingest(verbose: bool = True) -> dict:
    if not _KEY:
        if verbose:
            print("  BALLDONTLIE_KEY not set — skipping")
        return {"updated": 0}
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT id, match_date, home_team, away_team FROM matches
                WHERE status='finished' AND home_score IS NOT NULL
                  AND tournament ILIKE %s AND match_date >= %s
                  AND (home_xg IS NULL OR away_xg IS NULL)
                ORDER BY match_date
                """, ("%World Cup%", "2026-06-01")).fetchall()
    except Exception as exc:
        print(f"  balldontlie ingest: DB unavailable: {exc}")
        return {"updated": 0}
    gs = games()
    if verbose:
        print(f"  balldontlie: {len(gs)} games for season {_SEASON}; {len(rows)} matches need xG")
    n = 0
    for mid, d, home, away in rows:
        day = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
        g = find_game(home, away, day, cache=gs)
        if not g:
            if verbose:
                print(f"  no BDL game: {home} v {away} {day}")
            continue
        xg = game_xg(g)
        if xg and xg[0] is not None and xg[1] is not None:
            with connect() as conn:
                conn.execute("UPDATE matches SET home_xg=%s, away_xg=%s WHERE id=%s",
                             (float(xg[0]), float(xg[1]), mid))
            n += 1
            if verbose:
                print(f"  {home} {xg[0]:.2f}-{xg[1]:.2f} {away} xG")
        time.sleep(_PACE)
    if verbose:
        print(f"  balldontlie: wrote xG for {n}/{len(rows)} games")
    return {"updated": n, "candidates": len(rows)}


def _probe():
    gs = games()
    print(f"games season {_SEASON}: {len(gs)}")
    if gs:
        print("sample game JSON:\n", json.dumps(gs[0], indent=2)[:2000])
        gid = gs[0].get("id")
        for path in ("game_team_stats", "team_game_stats"):
            d = _get(path, {"game_ids[]": gid})
            print(f"\n{path} ->", json.dumps(d, indent=2)[:1500])


if __name__ == "__main__":
    print("configured:", configured(), "| base:", _BASE, "| season:", _SEASON)
    if "--probe" in sys.argv:
        _probe()
    else:
        print(ingest())
