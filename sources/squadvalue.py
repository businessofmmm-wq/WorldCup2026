"""
National-team squad market value as a club-derived talent signal.

Squad value aggregates club-football player quality into one team number — the one
thing Elo/Dixon-Coles (which see only international *results*) structurally cannot:
a side that has just regenerated its squad, or a debutant-heavy team. Stored in
team_market_value; consumed only as an optional, backtest-gated strength prior.

This seed is the WC2026 field as valued by Transfermarkt (June 2026, via
planetfootball.com — Transfermarkt itself is fetch-blocked in this environment).
Values are a STATIC snapshot in EUR millions; a production version should ingest
as-of-date values for a fully leakage-free historical walk-forward. Refresh by
editing _SEED or pointing ingest() at a live feed.
"""
from __future__ import annotations
import datetime as dt

from db import connect
from sources import sportsdb as _sportsdb

_AS_OF = dt.date(2026, 6, 14)

# Transfermarkt squad market value (EUR millions), WC2026 field, 2026-06-14.
_SEED = {
    "France": 1520, "England": 1360, "Spain": 1220, "Portugal": 1010, "Germany": 947,
    "Brazil": 928.2, "Argentina": 807.5, "Netherlands": 754.2, "Norway": 589.9,
    "Belgium": 547.5, "Ivory Coast": 522.1, "Senegal": 478.1, "Turkey": 473.7,
    "Morocco": 447.7, "Sweden": 406.08, "Croatia": 387.3, "United States": 385.6,
    "Ecuador": 368.7, "Uruguay": 359.3, "Switzerland": 332.5, "Colombia": 302.35,
    "Japan": 270.85, "Algeria": 256.9, "Austria": 245.2, "Ghana": 234.5,
    "Canada": 198.65, "Mexico": 191.85, "Czech Republic": 188.18, "Scotland": 170.25,
    "Paraguay": 153.65, "Bosnia & Herzegovina": 146.4, "DR Congo": 143.9,
    "South Korea": 139.05, "Egypt": 116.48, "Uzbekistan": 85.33, "Australia": 77.45,
    "Tunisia": 69.95, "Haiti": 55.9, "Cape Verde": 49.25, "South Africa": 49.25,
    "Saudi Arabia": 40.68, "Panama": 34.55, "New Zealand": 34.45, "Iran": 32.05,
    "Curacao": 25.78, "Iraq": 21.2, "Jordan": 20.3, "Qatar": 19.93,
}

# planetfootball spelling -> martj42/DB canonical, where they differ.
_NAME = {"Bosnia & Herzegovina": "Bosnia and Herzegovina", "Curacao": "Curaçao"}


def _canon(name: str) -> str:
    return _sportsdb._canon(_NAME.get(name, name))


def ensure_table() -> None:
    with connect() as c:
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS team_market_value (
                team    TEXT NOT NULL,
                value_m REAL NOT NULL,
                as_of   DATE NOT NULL,
                PRIMARY KEY (team, as_of)
            )
            """
        )


def ingest(verbose: bool = True) -> dict:
    ensure_table()
    with connect() as c:
        in_db = {r[0] for r in c.execute("SELECT DISTINCT home_team FROM matches").fetchall()}
        in_db |= {r[0] for r in c.execute("SELECT DISTINCT away_team FROM matches").fetchall()}
    n, miss = 0, []
    with connect() as c:
        for name, val in _SEED.items():
            t = _canon(name)
            if t not in in_db:
                miss.append(t)
                continue
            c.execute(
                """INSERT INTO team_market_value (team, value_m, as_of) VALUES (%s,%s,%s)
                   ON CONFLICT (team, as_of) DO UPDATE SET value_m = EXCLUDED.value_m""",
                (t, float(val), _AS_OF),
            )
            n += 1
    if verbose:
        print(f"  squad value: {n}/{len(_SEED)} teams matched to DB")
        if miss:
            print("  unmatched (check name mapping):", miss)
    return {"matched": n, "unmatched": miss}


def load(as_of=None) -> dict:
    with connect() as c:
        return {t: v for t, v in
                c.execute("SELECT team, value_m FROM team_market_value").fetchall()}


if __name__ == "__main__":
    print(ingest())
