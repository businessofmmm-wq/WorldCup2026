"""
Live fixtures + results via football-data.org v4 API.

Provides a drop-in `ingest(verbose=True)` function matching the style of
`sources/sportsdb.py`. If no API token is configured, or the API fails, this
module falls back to `sources.sportsdb.ingest()` so the site never goes dark.
"""
from __future__ import annotations
import os
import datetime as dt
import requests
from typing import Optional

import config
from db import connect

# Reuse the sportsdb canonicalisation helpers and conservative name map.
from sources import sportsdb as _sportsdb

_FD_BASE = os.environ.get("FOOTBALLDATA_BASE", "https://api.football-data.org/v4")
_FD_TOKEN = os.environ.get("WCPA_FOOTBALLDATA_TOKEN") or os.environ.get("FOOTBALLDATA_TOKEN")
# Competition code for the FIFA World Cup; sensible default 'WC' (football-data uses codes)
_FD_COMP = os.environ.get("WCPA_FOOTBALLDATA_COMP", "WC")

_UA = {"User-Agent": "WorldCup2026-Predictor/1.0"}


def _hdrs():
    h = dict(_UA)
    if _FD_TOKEN:
        h["X-Auth-Token"] = _FD_TOKEN
    return h


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{_FD_BASE.rstrip('/')}/{path.lstrip('/')}"
    resp = requests.get(url, headers=_hdrs(), params=params or {}, timeout=30)
    resp.raise_for_status()
    return resp.json() or {}


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_match(m: dict) -> dict:
    """Normalise a football-data.org match object to the engine's shape."""
    # home/away names in {'team': {'name': 'Country'}}
    home = (m.get("homeTeam") or {}).get("name")
    away = (m.get("awayTeam") or {}).get("name")
    # UTC datetime like 2026-11-20T16:00:00Z
    date_s = m.get("utcDate") or m.get("scheduled")
    hs = _to_int((m.get("score") or {}).get("fullTime", {}).get("home"))
    as_ = _to_int((m.get("score") or {}).get("fullTime", {}).get("away"))
    tournament = (m.get("competition") or {}).get("name") or "FIFA World Cup"
    return {"home": home, "away": away, "date": date_s, "home_score": hs,
            "away_score": as_, "tournament": tournament}


def upcoming() -> list[dict]:
    """Fetch scheduled/ongoing World Cup matches from football-data.org.
    Returns a list of raw match dicts. Raises on HTTP errors.
    """
    # football-data supports competition code like 'WC' at /competitions/{code}/matches
    try:
        data = _get(f"competitions/{_FD_COMP}/matches", params={"status": "SCHEDULED"})
        return data.get("matches") or []
    except Exception:
        # bubble up so callers can decide, but keep parity with sportsdb usage
        raise


def recent_results() -> list[dict]:
    """Fetch recently finished World Cup matches from football-data.org."""
    try:
        data = _get(f"competitions/{_FD_COMP}/matches", params={"status": "FINISHED"})
        return data.get("matches") or []
    except Exception:
        raise


def _store(matches: list[dict], status: str) -> int:
    """Store normalized matches into the `matches` table similarly to sportsdb._store.
    Best-effort, idempotent upserts with ±1 day match date fuzzing.
    """
    from models import field_2026
    n = 0
    with connect() as conn:
        for m in matches:
            row = _parse_match(m)
            home = _sportsdb._canon(row.get("home"))
            away = _sportsdb._canon(row.get("away"))
            date_s = row.get("date")
            if not (home and away and date_s):
                continue
            try:
                # strip time portion if present to get a date
                d = dt.date.fromisoformat(date_s[:10])
            except Exception:
                continue
            hs = row.get("home_score")
            as_ = row.get("away_score")
            row_status = "finished" if (hs is not None and as_ is not None) else status
            tournament = row.get("tournament")
            if "World Cup" in tournament:
                for t in (home, away):
                    if t not in field_2026.FIELD:
                        print(f"  ! footballdata name not in the 48-team field: {t!r} "
                              f"({home} v {away} {date_s}) — check NAME_MAP")
            existing = conn.execute(
                """
                SELECT id, home_score, away_score FROM matches
                WHERE home_team=%s AND away_team=%s AND tournament=%s
                  AND match_date BETWEEN %s AND %s
                ORDER BY abs(match_date - %s) LIMIT 1
                """,
                (home, away, tournament, d - dt.timedelta(days=1), d + dt.timedelta(days=1), d),
            ).fetchone()
            if existing:
                mid, old_hs, old_as = existing
                if hs is None and old_hs is not None:
                    continue
                if (hs, as_) == (old_hs, old_as) and hs is not None:
                    continue
                conn.execute(
                    "UPDATE matches SET home_score=%s, away_score=%s, status=%s WHERE id=%s",
                    (hs, as_, row_status, mid),
                )
            else:
                conn.execute(
                    "INSERT INTO matches (match_date, home_team, away_team, home_score, away_score, tournament, neutral, source, status) VALUES (%s,%s,%s,%s,%s,%s,TRUE,'footballdata',%s)",
                    (d, home, away, hs, as_, tournament, row_status),
                )
            n += 1
    return n


# Simple, short-lived cache to speed repeated lookups
_CACHE = {"at": 0.0, "matches": None}
_TTL = 120.0


def _all_matches() -> list[dict]:
    import time
    if _CACHE["matches"] is not None and time.time() - _CACHE["at"] < _TTL:
        return _CACHE["matches"]
    try:
        matches = (upcoming() or []) + (recent_results() or [])
    except Exception:
        matches = []
    _CACHE.update(at=time.time(), matches=matches)
    return matches


def find_event_id(home: str, away: str, date) -> Optional[str]:
    """Resolve a fixture to an identifier if available. football-data.org provides
    internal `id` fields on matches; return the match id when matched by name+date.
    Never raises.
    """
    try:
        d = date if isinstance(date, dt.date) else dt.date.fromisoformat(str(date))
    except Exception:
        return None
    try:
        matches = _all_matches()
    except Exception:
        return None
    h, a = home.lower(), away.lower()
    for m in matches:
        mh = _sportsdb._canon((m.get("homeTeam") or {}).get("name", "")).lower()
        ma = _sportsdb._canon((m.get("awayTeam") or {}).get("name", "")).lower()
        try:
            md = dt.date.fromisoformat((m.get("utcDate") or m.get("scheduled") or "")[:10])
        except Exception:
            continue
        if abs((md - d).days) <= 1 and mh == h and ma == a:
            return m.get("id") or m.get("matchId") or None
    return None


def ingest(verbose: bool = True) -> dict:
    """Top-level ingest: attempt football-data.org first; on any failure, fall
    back to TheSportsDB via `sources.sportsdb.ingest()` so downstream systems keep running.
    """
    if not _FD_TOKEN:
        if verbose:
            print("  WCPA_FOOTBALLDATA_TOKEN not set — falling back to TheSportsDB")
        return {"fallback": True, "sportsdb": _sportsdb.ingest(verbose=verbose)}
    up = res = []
    try:
        up = upcoming()
    except Exception as exc:
        if verbose:
            print(f"  football-data upcoming failed: {exc}")
    try:
        res = recent_results()
    except Exception as exc:
        if verbose:
            print(f"  football-data recent failed: {exc}")
    if not up and not res:
        if verbose:
            print("  No matches fetched from football-data.org — falling back to sportsdb")
        return {"fallback": True, "sportsdb": _sportsdb.ingest(verbose=verbose)}
    n_up = _store(up, "scheduled")
    n_res = _store(res, "finished")
    if verbose:
        print(f"  footballdata feed: {n_up} upcoming, {n_res} recent results stored")
    return {"upcoming": n_up, "results": n_res}


if __name__ == "__main__":
    res = ingest()
    print(res)
    print('\n  Next World Cup fixtures:')
    # Prefer footballdata upcoming if available; fall back to sportsdb upcoming
    matches = []
    if not res.get('fallback'):
        try:
            matches = upcoming()[:12]
        except Exception:
            matches = []
    if not matches:
        try:
            matches = _sportsdb.upcoming()[:12]
        except Exception:
            matches = []
    for m in matches:
        # compatibility: football-data.org vs sportsdb shape
        if isinstance(m, dict) and 'utcDate' in m:
            d = (m.get('utcDate') or '')[:10]
            ht = _sportsdb._canon((m.get('homeTeam') or {}).get('name', ''))
            at = _sportsdb._canon((m.get('awayTeam') or {}).get('name', ''))
        else:
            # sportsdb event shape
            d = (m.get('dateEvent') or '')
            ht = _sportsdb._canon(m.get('strHomeTeam'))
            at = _sportsdb._canon(m.get('strAwayTeam'))
        print(f"   {d} {ht} v {at}")
