"""
World Cup fixture reconciliation.

The three fixture inflows disagree on date conventions for the same tie:
martj42's results.csv records the LOCAL matchday, football-data.org's utcDate
is the UTC day (evening kickoffs in the Americas land on the next UTC day),
and hand-added schedule rows have used either. Each source upserts on an
exact (match_date, home, away, tournament) key, so the same tie can end up
as two rows one day apart — a played result then lands on one twin while the
schedule twin sits unplayed forever, and once both twins carry the score the
match is double-counted by Elo/Dixon-Coles training.

`reconcile()` merges those twins idempotently: one row per tie keeps the
richest fields (score wins over NULL, venue wins over bare, local matchday
wins over UTC day), then `status` is normalised off the score and `neutral`
is corrected for host nations playing at home. Safe to run after every
ingest — it no-ops on a clean table.
"""
from __future__ import annotations
import datetime as dt

from db import connect

WC_START = dt.date(2026, 6, 1)

# Host teams whose "neutral"-flagged games in their own country are really home games.
_HOSTS = {"United States", "Mexico", "Canada"}


def _pick_keeper(a: dict, b: dict) -> tuple[dict, dict]:
    """Order a twin pair as (keeper, donor). Prefer the row with venue data
    (the schedule rows are the richest), then the martj42/local-date row,
    then the earlier date (the local matchday of an evening kickoff)."""
    for key in (
        lambda r: bool(r["city"]),
        lambda r: r["source"] == "martj42",
        lambda r: r["match_date"] == min(a["match_date"], b["match_date"]),
    ):
        ka, kb = key(a), key(b)
        if ka != kb:
            return (a, b) if ka else (b, a)
    return (a, b) if a["id"] < b["id"] else (b, a)


def _merge_pair(conn, keeper: dict, donor: dict, verbose: bool) -> None:
    reversed_ = keeper["home_team"] != donor["home_team"]
    d_hs, d_as = donor["home_score"], donor["away_score"]
    if reversed_:
        d_hs, d_as = d_as, d_hs
    hs, as_ = keeper["home_score"], keeper["away_score"]
    if hs is None and d_hs is not None:
        hs, as_ = d_hs, d_as
    elif None not in (hs, d_hs) and (hs, as_) != (d_hs, d_as):
        print(f"  ! score conflict {keeper['home_team']} v {keeper['away_team']}: "
              f"keeping {hs}-{as_}, discarding {d_hs}-{d_as}")
    city = keeper["city"] or donor["city"]
    country = keeper["country"] or donor["country"]
    status = "finished" if hs is not None else "scheduled"
    conn.execute(
        "UPDATE matches SET home_score=%s, away_score=%s, city=%s, country=%s, "
        "status=%s WHERE id=%s",
        (hs, as_, city, country, status, keeper["id"]))
    conn.execute("DELETE FROM matches WHERE id=%s", (donor["id"],))
    if verbose:
        score = f"{hs}-{as_}" if hs is not None else "unplayed"
        print(f"  merged {keeper['home_team']} v {keeper['away_team']} "
              f"({donor['match_date']} -> {keeper['match_date']}, {score})")


def reconcile(verbose: bool = True) -> dict:
    """Merge duplicate WC-2026 fixture rows; fix status + host neutral flags."""
    n = {"merged": 0, "status_fixed": 0, "neutral_fixed": 0}
    with connect() as conn:
        cols = ("id", "match_date", "home_team", "away_team", "home_score",
                "away_score", "city", "country", "neutral", "source", "status")
        rows = [dict(zip(cols, r)) for r in conn.execute(
            f"SELECT {', '.join(cols)} FROM matches "
            "WHERE tournament='FIFA World Cup' AND match_date >= %s "
            "ORDER BY match_date, id", (WC_START,)).fetchall()]

        # Group by unordered team pair; merge rows within 1 day of each other.
        # A legitimate rematch (group stage + final) is weeks apart, never 1 day.
        by_pair: dict[frozenset, list[dict]] = {}
        for r in rows:
            by_pair.setdefault(frozenset((r["home_team"], r["away_team"])), []).append(r)
        deleted: set[int] = set()
        for group in by_pair.values():
            group.sort(key=lambda r: (r["match_date"], r["id"]))
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    if a["id"] in deleted or b["id"] in deleted:
                        continue
                    if abs((a["match_date"] - b["match_date"]).days) > 1:
                        continue
                    keeper, donor = _pick_keeper(a, b)
                    _merge_pair(conn, keeper, donor, verbose)
                    deleted.add(donor["id"])
                    # keep the keeper's dict current for a possible third twin
                    if keeper["home_score"] is None and donor["home_score"] is not None:
                        keeper["home_score"], keeper["away_score"] = (
                            donor["home_score"], donor["away_score"])
                    keeper["city"] = keeper["city"] or donor["city"]
                    keeper["country"] = keeper["country"] or donor["country"]
                    n["merged"] += 1

        # status must agree with the score (the imported schedule mis-tags
        # unplayed fixtures as 'finished'; the site keys off the score, but a
        # consistent status keeps every other consumer honest).
        cur = conn.execute(
            "UPDATE matches SET status='scheduled' WHERE tournament='FIFA World Cup' "
            "AND match_date >= %s AND home_score IS NULL AND status='finished'",
            (WC_START,))
        n["status_fixed"] += cur.rowcount
        cur = conn.execute(
            "UPDATE matches SET status='finished' WHERE tournament='FIFA World Cup' "
            "AND match_date >= %s AND home_score IS NOT NULL AND status='scheduled'",
            (WC_START,))
        n["status_fixed"] += cur.rowcount

        # A host nation playing in its own country is a HOME game, not neutral
        # (football-data inserts everything as neutral=TRUE; Elo's home
        # advantage should apply for the hosts).
        for host in _HOSTS:
            cur = conn.execute(
                "UPDATE matches SET neutral=(home_team<>%s) "
                "WHERE tournament='FIFA World Cup' AND match_date >= %s "
                "AND country=%s AND home_team=%s AND neutral",
                (host, WC_START, host, host))
            n["neutral_fixed"] += cur.rowcount
    if verbose and any(n.values()):
        print(f"  reconcile: {n['merged']} twins merged, "
              f"{n['status_fixed']} status fixed, {n['neutral_fixed']} neutral fixed")
    return n


if __name__ == "__main__":
    print(reconcile())
