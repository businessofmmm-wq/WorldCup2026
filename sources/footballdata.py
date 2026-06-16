"""
Live fixtures + results via football-data.org v4 API.

Provides a drop-in `ingest(verbose=True)` function matching the style of
`sources/sportsdb.py`. If no API token is configured, or the API fails, this
module falls back to `sources.sportsdb.ingest()` so the site never goes dark.

Reliability: a single request pulls the WHOLE competition and each match is
classified by its OWN status (SCHEDULED/TIMED -> scheduled, IN_PLAY/PAUSED ->
live, FINISHED -> finished). That avoids the status-filter gap that hid TIMED
and in-play games, and means every run BACKFILLS any finished game an earlier
(missed) poll skipped — so late-night fixtures can't be permanently lost.
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

# football-data.org status -> our coarse state.
_LIVE_STATUSES = {"IN_PLAY", "PAUSED", "SUSPENDED"}
_FINAL_STATUSES = {"FINISHED"}


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


def _status_of(m: dict) -> str:
    """Map a football-data match to scheduled | live | finished using its own status."""
    st = (m.get("status") or "").upper()
    if st in _FINAL_STATUSES:
        return "finished"
    if st in _LIVE_STATUSES:
        return "live"
    return "scheduled"   # SCHEDULED, TIMED, POSTPONED, CANCELLED, AWARDED…


def _parse_match(m: dict) -> dict:
    """Normalise a football-data.org match object to the engine's shape."""
    home = (m.get("homeTeam") or {}).get("name")
    away = (m.get("awayTeam") or {}).get("name")
    date_s = m.get("utcDate") or m.get("scheduled")
    hs = _to_int((m.get("score") or {}).get("fullTime", {}).get("home"))
    as_ = _to_int((m.get("score") or {}).get("fullTime", {}).get("away"))
    tournament = (m.get("competition") or {}).get("name") or "FIFA World Cup"
    return {"home": home, "away": away, "date": date_s, "home_score": hs,
            "away_score": as_, "tournament": tournament}


def all_matches() -> list[dict]:
    """Every WC match in ONE request — no status filter, so SCHEDULED, TIMED,
    IN_PLAY, PAUSED and FINISHED all come back and are classified locally. One
    call per poll is well inside the free 10 req/min budget. Raises on HTTP error."""
    data = _get(f"competitions/{_FD_COMP}/matches")
    return data.get("matches") or []


def upcoming() -> list[dict]:
    """Scheduled/near-term WC matches (SCHEDULED + TIMED), classified locally."""
    try:
        return [m for m in all_matches() if _status_of(m) == "scheduled"]
    except Exception:
        raise


def recent_results() -> list[dict]:
    """Finished WC matches, classified locally."""
    try:
        return [m for m in all_matches() if _status_of(m) == "finished"]
    except Exception:
        raise


def _store(matches: list[dict]) -> dict:
    """Upsert matches into the `matches` table, each with its own derived status.
    Idempotent, with ±1 day match-date fuzzing; never overwrites a real score with
    NULL (guards a flaky in-play payload); ignores placeholder scores on unstarted
    games. Returns counts per state."""
    from models import field_2026
    n = {"finished": 0, "live": 0, "scheduled": 0}
    with connect() as conn:
        for m in matches:
            row = _parse_match(m)
            status = _status_of(m)
            home = _sportsdb._canon(row.get("home"))
            away = _sportsdb._canon(row.get("away"))
            date_s = row.get("date")
            if not (home and away and date_s):
                continue
            try:
                d = dt.date.fromisoformat(date_s[:10])
            except Exception:
                continue
            hs = row.get("home_score")
            as_ = row.get("away_score")
            if status == "scheduled":
                hs = as_ = None   # ignore any placeholder score on an unstarted game
            tournament = row.get("tournament")
            if "World Cup" in tournament:
                for t in (home, away):
                    if t not in field_2026.FIELD:
                        print(f"  ! footballdata name not in the 48-team field: {t!r} "
                              f"({home} v {away} {date_s}) — check NAME_MAP")
            existing = conn.execute(
                """
                SELECT id, home_score, away_score, status FROM matches
                WHERE home_team=%s AND away_team=%s AND tournament=%s
                  AND match_date BETWEEN %s AND %s
                ORDER BY abs(match_date - %s) LIMIT 1
                """,
                (home, away, tournament, d - dt.timedelta(days=1), d + dt.timedelta(days=1), d),
            ).fetchone()
            if existing:
                mid, old_hs, old_as, old_status = existing
                if hs is None and old_hs is not None:
                    continue   # flaky regression — keep the real score
                if (hs, as_) == (old_hs, old_as) and status == old_status:
                    continue   # nothing changed
                conn.execute(
                    "UPDATE matches SET home_score=%s, away_score=%s, status=%s WHERE id=%s",
                    (hs, as_, status, mid),
                )
            else:
                conn.execute(
                    "INSERT INTO matches (match_date, home_team, away_team, home_score, away_score, tournament, neutral, source, status) VALUES (%s,%s,%s,%s,%s,%s,TRUE,'footballdata',%s)",
                    (d, home, away, hs, as_, tournament, status),
                )
            n[status] += 1
    return n


# Simple, short-lived cache to speed repeated lookups
_CACHE = {"at": 0.0, "matches": None}
_TTL = 120.0


def _all_matches() -> list[dict]:
    import time
    if _CACHE["matches"] is not None and time.time() - _CACHE["at"] < _TTL:
        return _CACHE["matches"]
    try:
        matches = all_matches()
    except Exception:
        matches = []
    _CACHE.update(at=time.time(), matches=matches)
    return matches


def find_event_id(home: str, away: str, date) -> Optional[str]:
    """Resolve a fixture to a football-data match id by name+date. Never raises."""
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
    """Top-level ingest: pull the whole competition from football-data.org and
    upsert every match by its own status. On any failure (or no token), fall back
    to TheSportsDB via `sources.sportsdb.ingest()` so the site never goes dark."""
    if not _FD_TOKEN:
        if verbose:
            print("  WCPA_FOOTBALLDATA_TOKEN not set — falling back to TheSportsDB")
        return {"fallback": True, "sportsdb": _sportsdb.ingest(verbose=verbose)}
    try:
        ms = all_matches()
    except Exception as exc:
        if verbose:
            print(f"  football-data fetch failed ({exc}) — falling back to sportsdb")
        return {"fallback": True, "sportsdb": _sportsdb.ingest(verbose=verbose)}
    if not ms:
        if verbose:
            print("  football-data returned no matches — falling back to sportsdb")
        return {"fallback": True, "sportsdb": _sportsdb.ingest(verbose=verbose)}
    n = _store(ms)
    if verbose:
        print(f"  footballdata feed: {n['finished']} finished, {n['live']} live, "
              f"{n['scheduled']} scheduled (of {len(ms)} fetched)")
    return n


if __name__ == "__main__":
    res = ingest()
    print(res)
    print('\n  Next World Cup fixtures:')
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
        if isinstance(m, dict) and 'utcDate' in m:
            d = (m.get('utcDate') or '')[:10]
            ht = _sportsdb._canon((m.get('homeTeam') or {}).get('name', ''))
            at = _sportsdb._canon((m.get('awayTeam') or {}).get('name', ''))
        else:
            d = (m.get('dateEvent') or '')
            ht = _sportsdb._canon(m.get('strHomeTeam'))
            at = _sportsdb._canon(m.get('strAwayTeam'))
        print(f"   {d} {ht} v {at}")
