"""
Historical results ingestion.

Source: martj42/international_results — the canonical public dataset of every
men's full international since the first one (Scotland 0-0 England, 1872).
Three CSVs: results, shootouts, goalscorers. We pull results + shootouts (the
goalscorers file is huge and not needed for team-level prediction yet).

Fetched with `requests`, parsed with the stdlib `csv` module (no pandas), and
bulk-upserted into Postgres in batches.
"""
from __future__ import annotations
import csv
import io
import datetime as dt

import requests

import config
from db import connect, upsert_team

# A few country -> confederation hints for the headline nations. Not exhaustive
# (the dataset has 300+ "teams" incl. defunct states); the model doesn't need
# confederation to work, it's only used for nicer reporting / grouping.
_CONFED = {
    "UEFA": ["England", "Scotland", "Wales", "Northern Ireland", "Republic of Ireland",
             "France", "Germany", "Spain", "Italy", "Portugal", "Netherlands", "Belgium",
             "Croatia", "Denmark", "Switzerland", "Poland", "Sweden", "Norway", "Austria",
             "Serbia", "Ukraine", "Czech Republic", "Turkey", "Greece", "Russia", "Hungary"],
    "CONMEBOL": ["Brazil", "Argentina", "Uruguay", "Colombia", "Chile", "Peru",
                 "Paraguay", "Ecuador", "Bolivia", "Venezuela"],
    "CONCACAF": ["United States", "Mexico", "Canada", "Costa Rica", "Honduras",
                 "Jamaica", "Panama", "El Salvador"],
    "CAF": ["Nigeria", "Senegal", "Egypt", "Cameroon", "Ghana", "Morocco", "Algeria",
            "Tunisia", "Ivory Coast", "South Africa", "Mali"],
    "AFC": ["Japan", "South Korea", "Australia", "Iran", "Saudi Arabia", "Qatar",
            "Iraq", "United Arab Emirates", "China PR", "Uzbekistan"],
    "OFC": ["New Zealand", "Fiji", "Tahiti", "Solomon Islands", "New Caledonia"],
}
_TEAM_CONFED = {team: conf for conf, teams in _CONFED.items() for team in teams}


def _fetch_csv(url: str) -> list[dict]:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return list(csv.DictReader(io.StringIO(resp.text)))


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _to_date(v):
    try:
        return dt.date.fromisoformat(v)
    except (TypeError, ValueError):
        return None


def ingest(verbose: bool = True) -> dict:
    """Pull results + shootouts into Postgres. Returns counts."""
    if verbose:
        print("  fetching results.csv ...")
    rows = _fetch_csv(config.RESULTS_CSV)
    if verbose:
        print(f"  {len(rows):,} matches downloaded; upserting ...")

    teams_seen: set[str] = set()
    match_batch = []
    n_matches = 0

    with connect() as conn:
        for r in rows:
            d = _to_date(r["date"])
            if d is None:
                continue
            home, away = r["home_team"].strip(), r["away_team"].strip()
            teams_seen.add(home)
            teams_seen.add(away)
            match_batch.append((
                d, home, away,
                _to_int(r["home_score"]), _to_int(r["away_score"]),
                r["tournament"].strip(), r.get("city", "").strip(),
                r.get("country", "").strip(),
                str(r.get("neutral", "")).upper() == "TRUE",
                "martj42",
            ))
            if len(match_batch) >= 1000:
                n_matches += _flush_matches(conn, match_batch)
                match_batch.clear()
        if match_batch:
            n_matches += _flush_matches(conn, match_batch)

        # Register teams (with confederation hints where known).
        for t in sorted(teams_seen):
            upsert_team(conn, t, _TEAM_CONFED.get(t))

    n_shoot = _ingest_shootouts(verbose)

    if verbose:
        print(f"  done: {n_matches:,} matches, {len(teams_seen):,} teams, {n_shoot:,} shootouts")
    return {"matches": n_matches, "teams": len(teams_seen), "shootouts": n_shoot}


def _flush_matches(conn, batch) -> int:
    """Bulk upsert a batch of finished historical matches."""
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO matches
                (match_date, home_team, away_team, home_score, away_score,
                 tournament, city, country, neutral, source, status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'finished')
            ON CONFLICT (match_date, home_team, away_team, tournament)
            DO UPDATE SET home_score = EXCLUDED.home_score,
                          away_score = EXCLUDED.away_score
            """,
            batch,
        )
    return len(batch)


def _ingest_shootouts(verbose: bool) -> int:
    try:
        rows = _fetch_csv(config.SHOOTOUTS_CSV)
    except Exception as exc:  # non-fatal
        if verbose:
            print(f"  shootouts skipped: {exc}")
        return 0
    batch = []
    for r in rows:
        d = _to_date(r["date"])
        if d is None:
            continue
        batch.append((d, r["home_team"].strip(), r["away_team"].strip(),
                      r.get("winner", "").strip() or None))
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO shootouts (match_date, home_team, away_team, winner)
            VALUES (%s,%s,%s,%s)
            ON CONFLICT (match_date, home_team, away_team)
            DO UPDATE SET winner = EXCLUDED.winner
            """,
            batch,
        )
    return len(batch)


if __name__ == "__main__":
    from db import init_schema
    init_schema()
    print(ingest())
