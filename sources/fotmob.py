"""
FotMob match-detail scraper — xG, shots, possession for World Cup games.

The free score feeds (football-data, sportsdb) have no xG. FotMob's public JSON
API does, and it's free. NOTE: FotMob blocks datacenter/cloud IPs, so this only
works run from a normal (residential) connection — i.e. locally on the engine PC,
NOT from the cloud workers or an agent sandbox (that's exactly why a desktop tool
like raycast_gfb works and a server probe 403s). If FotMob ever demands the signed
`x-mas` header, grab it from your browser DevTools (Network tab → any /api request)
and set FOTMOB_XMAS in .env.

What it does: for each finished WC2026 match missing xG, find the FotMob match id
for that day, pull its details, extract home/away xG, and write them into
matches.home_xg / matches.away_xg. Shots & possession are returned too (for a
future schema/feature) but not stored (no column yet). Best-effort; never fatal.

Run:  python -m sources.fotmob
"""
from __future__ import annotations
import os
import time
import datetime as dt

import requests

from db import connect
from sources import sportsdb as _sportsdb

_BASE = os.environ.get("FOTMOB_BASE", "https://www.fotmob.com/api")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
       "Accept": "application/json"}
_XMAS = os.environ.get("FOTMOB_XMAS", "").strip()

# FotMob uses its own country names; map the few that differ from our canon.
_FM_NAME = {
    "USA": "United States", "South Korea": "South Korea", "Korea Republic": "South Korea",
    "Czechia": "Czech Republic", "Cape Verde Islands": "Cape Verde", "Cape Verde": "Cape Verde",
    "Ivory Coast": "Ivory Coast", "Côte d'Ivoire": "Ivory Coast", "Turkiye": "Turkey",
    "Türkiye": "Turkey", "DR Congo": "DR Congo", "Curacao": "Curaçao",
}


def _canon(name: str) -> str:
    n = _FM_NAME.get((name or "").strip(), name)
    return _sportsdb._canon(n)


def _hdrs() -> dict:
    h = dict(_UA)
    if _XMAS:
        h["x-mas"] = _XMAS
    return h


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = requests.get(f"{_BASE.rstrip('/')}/{path.lstrip('/')}",
                         headers=_hdrs(), params=params or {}, timeout=25)
        r.raise_for_status()
        return r.json() or {}
    except Exception as exc:
        print(f"  fotmob {path} failed: {exc}")
        return {}


def matches_on(date: dt.date) -> list[dict]:
    """All matches FotMob lists for a UTC date, flattened with league name."""
    data = _get("matches", {"date": date.strftime("%Y%m%d")})
    out = []
    for lg in (data.get("leagues") or []):
        lname = lg.get("name") or ""
        for m in (lg.get("matches") or []):
            out.append({"id": m.get("id"), "league": lname,
                        "home": ((m.get("home") or {}).get("name")),
                        "away": ((m.get("away") or {}).get("name"))})
    return out


def find_match_id(home: str, away: str, date: dt.date) -> int | None:
    """Resolve a fixture to a FotMob match id (search the day and ±1)."""
    h, a = _canon(home).lower(), _canon(away).lower()
    for delta in (0, -1, 1):
        for m in matches_on(date + dt.timedelta(days=delta)):
            if (_canon(m["home"]).lower(), _canon(m["away"]).lower()) == (h, a) and m["id"]:
                return m["id"]
    return None


def _find_pair(obj, needles) -> list | None:
    """Recursively find a stat object {title/key ~ needle, stats:[home,away]}."""
    if isinstance(obj, dict):
        title = str(obj.get("title", "")).lower() + " " + str(obj.get("key", "")).lower()
        st = obj.get("stats")
        if any(nd in title for nd in needles) and isinstance(st, list) and len(st) == 2:
            return st
        for v in obj.values():
            r = _find_pair(v, needles)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_pair(v, needles)
            if r:
                return r
    return None


def _num(v):
    try:
        return float(str(v).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def match_stats(match_id: int) -> dict:
    """{xg:(h,a), possession:(h,a), shots:(h,a)} from a FotMob match (any may be None)."""
    d = _get("matchDetails", {"matchId": match_id})
    if not d:
        return {}
    xg = _find_pair(d, ("expected goals", "expected_goals", "xg"))
    pos = _find_pair(d, ("ball possession", "possession"))
    sh = _find_pair(d, ("total shots", "shots"))
    f = lambda p: (_num(p[0]), _num(p[1])) if p else None
    return {"xg": f(xg), "possession": f(pos), "shots": f(sh)}


def ingest(verbose: bool = True, sleep: float = 1.5) -> dict:
    """Backfill xG into `matches` for finished WC2026 games that lack it."""
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
        print(f"  fotmob ingest: DB unavailable: {exc}")
        return {"updated": 0}
    n = 0
    for mid_db, d, home, away in rows:
        day = d if isinstance(d, dt.date) else dt.date.fromisoformat(str(d)[:10])
        fmid = find_match_id(home, away, day)
        if not fmid:
            if verbose:
                print(f"  no FotMob id: {home} v {away} {day}")
            continue
        s = match_stats(fmid)
        xg = s.get("xg")
        if xg and xg[0] is not None and xg[1] is not None:
            with connect() as conn:
                conn.execute("UPDATE matches SET home_xg=%s, away_xg=%s WHERE id=%s",
                             (xg[0], xg[1], mid_db))
            n += 1
            if verbose:
                print(f"  {home} {xg[0]:.2f}-{xg[1]:.2f} {away} xG  (fotmob {fmid})")
        time.sleep(sleep)
    if verbose:
        print(f"  fotmob: wrote xG for {n}/{len(rows)} games")
    return {"updated": n, "candidates": len(rows)}


if __name__ == "__main__":
    print(ingest())
