"""
xG ingestion from StatsBomb open data.

StatsBomb publish free, shot-level event data (including each shot's expected
-goals value) for past World Cups. We sum shot xG per team per match to get
match-level xG, and write it onto the corresponding `matches` rows
(home_xg / away_xg). This is the "new stat measure" layer — once a match has
xG, models can weight performance by chances created rather than just goals.

Competition/season ids live in StatsBomb's `matches/<comp>/<season>.json`.
The events files are one JSON per match and fairly large, so ingestion is
rate-limited and resumable. Default: the most recent World Cup available.
"""
from __future__ import annotations
import datetime as dt

import requests

import config
from db import connect

_UA = {"User-Agent": "WorldCup2026-Predictor/1.0"}


def _get(url: str):
    resp = requests.get(url, headers=_UA, timeout=60)
    resp.raise_for_status()
    return resp.json()


def seasons_for(comp_id: int) -> list[int]:
    comps = _get(f"{config.STATSBOMB_BASE}/competitions.json")
    return sorted({c["season_id"] for c in comps if c["competition_id"] == comp_id})


def matches_for(comp_id: int, season_id: int) -> list[dict]:
    return _get(f"{config.STATSBOMB_BASE}/matches/{comp_id}/{season_id}.json")


def _match_xg(match_id: int) -> dict[str, float]:
    """Return {team_name: total shot xG} for a single match."""
    events = _get(f"{config.STATSBOMB_BASE}/events/{match_id}.json")
    xg: dict[str, float] = {}
    for ev in events:
        if ev.get("type", {}).get("name") != "Shot":
            continue
        team = ev.get("team", {}).get("name")
        val = ev.get("shot", {}).get("statsbomb_xg")
        if team and val is not None:
            xg[team] = xg.get(team, 0.0) + float(val)
    return xg


def ingest(comp_id: int | None = None, season_id: int | None = None,
           limit: int | None = None, verbose: bool = True) -> dict:
    comp_id = comp_id or config.STATSBOMB_WC_COMP
    if season_id is None:
        seasons = seasons_for(comp_id)
        if not seasons:
            return {"matches": 0, "note": "no seasons"}
        season_id = seasons[-1]  # most recent World Cup available
    matches = matches_for(comp_id, season_id)
    if limit:
        matches = matches[:limit]
    if verbose:
        print(f"  StatsBomb comp {comp_id} season {season_id}: {len(matches)} matches")

    n = 0
    with connect() as conn:
        for m in matches:
            try:
                xg = _match_xg(m["match_id"])
            except Exception as exc:
                if verbose:
                    print(f"   match {m['match_id']} skipped: {exc}")
                continue
            home = m["home_team"]["home_team_name"]
            away = m["away_team"]["away_team_name"]
            d = dt.date.fromisoformat(m["match_date"])
            hxg = xg.get(home)
            axg = xg.get(away)
            # store on the historical row if it exists; otherwise create one
            conn.execute(
                """
                INSERT INTO matches
                    (match_date, home_team, away_team, home_score, away_score,
                     home_xg, away_xg, tournament, neutral, source, status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'FIFA World Cup',TRUE,'statsbomb','finished')
                ON CONFLICT (match_date, home_team, away_team, tournament)
                DO UPDATE SET home_xg = COALESCE(EXCLUDED.home_xg, matches.home_xg),
                              away_xg = COALESCE(EXCLUDED.away_xg, matches.away_xg)
                """,
                (d, home, away,
                 m.get("home_score"), m.get("away_score"), hxg, axg),
            )
            n += 1
            if verbose and n % 10 == 0:
                print(f"   ...{n} matches with xG")
    if verbose:
        print(f"  done: {n} matches updated with xG")
    return {"matches": n, "comp": comp_id, "season": season_id}


if __name__ == "__main__":
    # quick smoke test: just the first few matches so it's fast
    print(ingest(limit=3))
