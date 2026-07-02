"""
Harvest knockout kickoff times + venues and fold them into the engine.

Two feeds, two strengths:
  * football-data.org `utcDate` carries the real kickoff timestamp for every
    match in the competition (including ties whose pairings are known but
    which KICKOFFS_UTC predates) — but no venue for this competition.
  * TheSportsDB eventsround (free key) carries strVenue/strCity/strCountry
    per tie for the knockout rounds — the venue data the DB rows lack when
    football-data inserted them.

What it does (idempotent, safe to re-run after every round is drawn):
  1. Merges every known-pair kickoff into models/schedule_2026.py
     KICKOFFS_UTC (existing entries win unless the feed moved a FUTURE
     kickoff; the file is regenerated in place, sorted by kickoff).
  2. Fills city/country on WC match rows that have none, matching by
     canonical team pair within ±1 day.
  3. Re-applies the host-nation neutral fix via sources.reconcile.

Run from the project root:  python tools/harvest_kickoffs.py
"""
from __future__ import annotations
import datetime as dt
import os
import re
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402  (loads .env for the football-data token)
import db      # noqa: E402
from sources import footballdata as fd          # noqa: E402
from sources import sportsdb as _sportsdb       # noqa: E402
from sources import reconcile as _reconcile     # noqa: E402
from models import schedule_2026                # noqa: E402

_SCHEDULE_PY = os.path.join(os.path.dirname(__file__), "..", "models", "schedule_2026.py")
_SPORTSDB_ROUNDS = (32, 16, 8, 4, 2, 1)   # knockout rounds; empty rounds just no-op

_HEADER = '''"""Auto-generated: 2026 World Cup kickoff times (UTC), all known pairings.

Group stage harvested from TheSportsDB eventsround; knockout rounds merged in
by tools/harvest_kickoffs.py from football-data.org utcDate as each round's
pairings become known. The front-end localises each time to the viewer's own
timezone. Re-run `python tools/harvest_kickoffs.py` after every round.
"""

# (home_team, away_team) -> ISO-8601 UTC kickoff
KICKOFFS_UTC = {
'''


def _canon(name: str | None) -> str | None:
    return _sportsdb._canon(name) if name else None


def harvest_kickoffs() -> dict[tuple[str, str], str]:
    """Known-pair kickoffs from football-data, canonically named."""
    out: dict[tuple[str, str], str] = {}
    for m in fd.all_matches():
        home = _canon((m.get("homeTeam") or {}).get("name"))
        away = _canon((m.get("awayTeam") or {}).get("name"))
        iso = m.get("utcDate")
        if home and away and iso:
            out[(home, away)] = iso.replace("+00:00", "Z")
    return out


def harvest_venues() -> dict[frozenset, tuple[str, str, str]]:
    """Known-pair venues from TheSportsDB: pair -> (city, country, kickoff)."""
    out: dict[frozenset, tuple[str, str, str]] = {}
    for rnd in _SPORTSDB_ROUNDS:
        try:
            r = requests.get(
                "https://www.thesportsdb.com/api/v1/json/3/eventsround.php",
                params={"id": 4429, "r": rnd, "s": 2026}, timeout=30)
            events = (r.json() or {}).get("events") or []
        except Exception:
            continue
        for e in events:
            home = _canon(e.get("strHomeTeam"))
            away = _canon(e.get("strAwayTeam"))
            city = (e.get("strCity") or "").split(",")[0].strip()
            country = (e.get("strCountry") or "").strip()
            ts = (e.get("strTimestamp") or "").strip()
            if home and away and city and country:
                out[frozenset((home, away))] = (city, country, ts)
    return out


def merge_schedule(kickoffs: dict[tuple[str, str], str], verbose: bool = True) -> int:
    """Fold new/changed kickoffs into KICKOFFS_UTC and rewrite schedule_2026.py."""
    merged = dict(schedule_2026.KICKOFFS_UTC)
    now_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    changed = 0
    for pair, iso in kickoffs.items():
        old = merged.get(pair)
        if old == iso:
            continue
        # Never rewrite history: only add unknown pairs or move FUTURE kickoffs.
        if old is None or old > now_iso:
            merged[pair] = iso
            changed += 1
            if verbose:
                verb = "moved" if old else "added"
                print(f"  {verb} kickoff {pair[0]} v {pair[1]} -> {iso}")
    if not changed:
        return 0
    lines = [_HEADER]
    for (h, a), iso in sorted(merged.items(), key=lambda kv: (kv[1], kv[0])):
        lines.append(f"    ({h!r}, {a!r}): {iso!r},\n")
    lines.append("}\n")
    with open(_SCHEDULE_PY, "w", encoding="utf-8") as fh:
        fh.writelines(lines)
    return changed


def enrich_venues(venues: dict[frozenset, tuple[str, str, str]],
                  verbose: bool = True) -> int:
    """Fill city/country on venue-less WC rows, matched by pair within ±1 day."""
    n = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, match_date, home_team, away_team FROM matches "
            "WHERE tournament='FIFA World Cup' AND match_date >= %s "
            "AND (city IS NULL OR city = '')", (_reconcile.WC_START,)).fetchall()
        for mid, d, home, away in rows:
            hit = venues.get(frozenset((home, away)))
            if not hit:
                continue
            city, country, ts = hit
            if ts:
                try:
                    ev_date = dt.date.fromisoformat(ts[:10])
                    if abs((ev_date - d).days) > 1:
                        continue
                except ValueError:
                    pass
            conn.execute("UPDATE matches SET city=%s, country=%s WHERE id=%s",
                         (city, country, mid))
            n += 1
            if verbose:
                print(f"  venue {home} v {away} ({d}) -> {city}, {country}")
    return n


def main() -> None:
    kickoffs = harvest_kickoffs()
    print(f"football-data: {len(kickoffs)} known-pair kickoffs")
    changed = merge_schedule(kickoffs)
    print(f"schedule_2026.py: {changed} entries merged")
    venues = harvest_venues()
    print(f"sportsdb: venues for {len(venues)} ties")
    filled = enrich_venues(venues)
    print(f"matches table: {filled} venues filled")
    _reconcile.reconcile()


if __name__ == "__main__":
    main()
