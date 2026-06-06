"""
International Elo rating engine.

Implements the World Football Elo Ratings method:
  - expected score from the rating difference (with home advantage),
  - update scaled by a tournament-importance K-factor,
  - a goal-difference multiplier so big wins move ratings more.

We replay every finished match in chronological order, snapshot each team's
rating into `elo_history`, and persist the final ratings into `team_ratings`.
These ratings are also returned in-memory so the predictor can use them
without a DB round-trip.
"""
from __future__ import annotations
import math

import config
from db import connect


def expected_score(rating_a: float, rating_b: float) -> float:
    """Win expectancy of A vs B (draw counts as half), logistic on 400."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _gd_multiplier(goal_diff: int) -> float:
    """World Football Elo goal-difference weighting."""
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11 + g) / 8.0


def _k_for(tournament: str | None) -> float:
    if not tournament:
        return config.ELO_K_DEFAULT
    # match on a prefix so "FIFA World Cup qualification" etc. resolve cleanly
    for key, k in config.ELO_K_BY_TOURNAMENT.items():
        if tournament == key:
            return k
    for key, k in config.ELO_K_BY_TOURNAMENT.items():
        if tournament.startswith(key):
            return k
    return config.ELO_K_DEFAULT


def compute(persist: bool = True, verbose: bool = True) -> dict[str, float]:
    """Replay history, return {team: elo}. Optionally write to the DB."""
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT match_date, home_team, away_team, home_score, away_score,
                   tournament, neutral
            FROM matches
            WHERE status='finished' AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
            ORDER BY match_date, id
            """
        ).fetchall()

    elo: dict[str, float] = {}
    last_match: dict[str, str] = {}
    counts: dict[str, int] = {}
    history: list[tuple] = []

    for d, home, away, hs, as_, tourn, neutral in rows:
        ra = elo.get(home, config.ELO_START)
        rb = elo.get(away, config.ELO_START)

        ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
        exp_home = expected_score(ra + ha, rb)

        if hs > as_:
            score_home = 1.0
        elif hs < as_:
            score_home = 0.0
        else:
            score_home = 0.5

        mult = _gd_multiplier(hs - as_) if config.ELO_USE_GD else 1.0
        k = _k_for(tourn) * config.ELO_K_SCALE * mult
        delta = k * (score_home - exp_home)

        elo[home] = ra + delta
        elo[away] = rb - delta
        counts[home] = counts.get(home, 0) + 1
        counts[away] = counts.get(away, 0) + 1
        last_match[home] = last_match[away] = d

        history.append((home, d, elo[home]))
        history.append((away, d, elo[away]))

    if verbose:
        print(f"  Elo computed over {len(rows):,} matches, {len(elo)} teams")

    if persist:
        _persist(elo, counts, last_match, history, verbose)
    return elo


def _persist(elo, counts, last_match, history, verbose):
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO team_ratings (team, elo, matches_count, last_match, updated_at)
            VALUES (%s,%s,%s,%s, now())
            ON CONFLICT (team) DO UPDATE
              SET elo = EXCLUDED.elo,
                  matches_count = EXCLUDED.matches_count,
                  last_match = EXCLUDED.last_match,
                  updated_at = now()
            """,
            [(t, elo[t], counts.get(t, 0), last_match.get(t)) for t in elo],
        )
        # elo_history can be large; keep only one row per team per date (latest)
        cur.execute("TRUNCATE elo_history")
        # collapse to last value per (team, date)
        seen: dict[tuple, float] = {}
        for team, d, val in history:
            seen[(team, d)] = val
        cur.executemany(
            "INSERT INTO elo_history (team, match_date, elo) VALUES (%s,%s,%s)",
            [(t, d, v) for (t, d), v in seen.items()],
        )
    if verbose:
        print(f"  persisted ratings + {len(seen):,} history points")


def top(n: int = 25) -> list[tuple[str, float, int]]:
    with connect() as conn:
        return conn.execute(
            """
            SELECT team, elo, matches_count FROM team_ratings
            WHERE last_match >= (CURRENT_DATE - INTERVAL '4 years')
            ORDER BY elo DESC LIMIT %s
            """,
            (n,),
        ).fetchall()


if __name__ == "__main__":
    compute()
    print("\n  Top 20 (active, last 4y):")
    for i, (t, e, c) in enumerate(top(20), 1):
        print(f"   {i:>2}. {t:<22} {e:7.1f}  ({c} matches)")
