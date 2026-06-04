"""
Live fixtures + results via TheSportsDB (free public key "3").

This is the real-time "inflow": upcoming World Cup fixtures, in-progress and
just-finished scores. New finished results are written into `matches` with
source 'sportsdb' so the next train run folds them into the ratings — the loop
that keeps predictions current as the tournament unfolds.
"""
from __future__ import annotations
import datetime as dt

import requests

import config
from db import connect

_UA = {"User-Agent": "WorldCup2026-Predictor/1.0"}


def _get(path: str) -> dict:
    resp = requests.get(f"{config.SPORTSDB_BASE}/{path}", headers=_UA, timeout=30)
    resp.raise_for_status()
    return resp.json() or {}


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def upcoming(league_id: str | None = None) -> list[dict]:
    """Next scheduled events for the World Cup league."""
    lid = league_id or config.SPORTSDB_WC_LEAGUE_ID
    return (_get(f"eventsnextleague.php?id={lid}") or {}).get("events") or []


def recent_results(league_id: str | None = None) -> list[dict]:
    """Last finished events for the World Cup league."""
    lid = league_id or config.SPORTSDB_WC_LEAGUE_ID
    return (_get(f"eventspastleague.php?id={lid}") or {}).get("events") or []


def _store(events: list[dict], status: str) -> int:
    n = 0
    with connect() as conn:
        for e in events:
            home = (e.get("strHomeTeam") or "").strip()
            away = (e.get("strAwayTeam") or "").strip()
            date_s = e.get("dateEvent")
            if not (home and away and date_s):
                continue
            try:
                d = dt.date.fromisoformat(date_s)
            except ValueError:
                continue
            hs = _to_int(e.get("intHomeScore"))
            as_ = _to_int(e.get("intAwayScore"))
            row_status = "finished" if (hs is not None and as_ is not None) else status
            tournament = (e.get("strLeague") or "FIFA World Cup").strip()
            conn.execute(
                """
                INSERT INTO matches
                    (match_date, home_team, away_team, home_score, away_score,
                     tournament, neutral, source, status)
                VALUES (%s,%s,%s,%s,%s,%s,TRUE,'sportsdb',%s)
                ON CONFLICT (match_date, home_team, away_team, tournament)
                DO UPDATE SET home_score = EXCLUDED.home_score,
                              away_score = EXCLUDED.away_score,
                              status = EXCLUDED.status
                """,
                (d, home, away, hs, as_, tournament, row_status),
            )
            n += 1
    return n


def ingest(verbose: bool = True) -> dict:
    up, res = [], []
    try:
        up = upcoming()
    except Exception as exc:
        if verbose:
            print(f"  upcoming skipped: {exc}")
    try:
        res = recent_results()
    except Exception as exc:
        if verbose:
            print(f"  results skipped: {exc}")
    n_up = _store(up, "scheduled")
    n_res = _store(res, "finished")
    if verbose:
        print(f"  live feed: {n_up} upcoming, {n_res} recent results stored")
    return {"upcoming": n_up, "results": n_res}


if __name__ == "__main__":
    print(ingest())
    print("\n  Next World Cup fixtures:")
    for e in upcoming()[:12]:
        print(f"   {e.get('dateEvent')} {e.get('strEvent')}")
