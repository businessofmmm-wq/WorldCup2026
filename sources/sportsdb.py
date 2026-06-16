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

# TheSportsDB team names -> the engine's canonical names (martj42 conventions).
# The feed's spelling drifts (USA, Korea Republic, Curacao…); storing a variant
# would silently fork a phantom team and the result would never reach the model.
NAME_MAP = {
    "USA": "United States", "United States of America": "United States",
    "Korea Republic": "South Korea", "Korea DPR": "North Korea",
    "IR Iran": "Iran", "Iran IR": "Iran",
    "Curacao": "Curaçao",
    "Cote d'Ivoire": "Ivory Coast", "Côte d'Ivoire": "Ivory Coast",
    "Turkiye": "Turkey", "Türkiye": "Turkey",
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Bosnia": "Bosnia and Herzegovina",
    "Cabo Verde": "Cape Verde", "Cape Verde Islands": "Cape Verde",
    "Congo DR": "DR Congo", "DR Congo (Zaire)": "DR Congo",
}


def _canon(name: str | None) -> str:
    name = (name or "").strip()
    return NAME_MAP.get(name, name)


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
    """Defensive write path for a feed that is both *skewed* and *flaky*:

    - dateEvent is the UTC calendar day, while the imported schedule carries the
      local matchday — a 01:00Z kickoff differs by a day, so an exact-date upsert
      would duplicate the fixture. An existing row within ±1 day claims the event
      instead (the schedule's date stays canonical).
    - a finished match can transiently reappear in `upcoming` with no score; a
      real score is therefore never overwritten with NULL.
    """
    from models import field_2026
    n = 0
    with connect() as conn:
        for e in events:
            home = _canon(e.get("strHomeTeam"))
            away = _canon(e.get("strAwayTeam"))
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
            if "World Cup" in tournament:
                for t in (home, away):
                    if t not in field_2026.FIELD:
                        print(f"  ! sportsdb name not in the 48-team field: {t!r} "
                              f"({home} v {away} {date_s}) — check NAME_MAP")
            row = conn.execute(
                """
                SELECT id, home_score, away_score FROM matches
                WHERE home_team=%s AND away_team=%s AND tournament=%s
                  AND match_date BETWEEN %s AND %s
                ORDER BY abs(match_date - %s) LIMIT 1
                """,
                (home, away, tournament,
                 d - dt.timedelta(days=1), d + dt.timedelta(days=1), d),
            ).fetchone()
            if row:
                mid, old_hs, old_as = row
                if hs is None and old_hs is not None:
                    continue                     # flaky feed regression — keep the result
                if (hs, as_) == (old_hs, old_as) and hs is not None:
                    continue                     # nothing new
                conn.execute(
                    "UPDATE matches SET home_score=%s, away_score=%s, status=%s "
                    "WHERE id=%s",
                    (hs, as_, row_status, mid))
            else:
                conn.execute(
                    """
                    INSERT INTO matches
                        (match_date, home_team, away_team, home_score, away_score,
                         tournament, neutral, source, status)
                    VALUES (%s,%s,%s,%s,%s,%s,TRUE,'sportsdb',%s)
                    """,
                    (d, home, away, hs, as_, tournament, row_status))
            n += 1
    return n


# Short-lived cache of the combined WC upcoming+recent feed. find_event_id() can be
# called once per completed fixture (e.g. during a static export); without this each
# call would re-pull two endpoints. One fetch per ~2 min process window is plenty.
_EVENTS_CACHE: dict = {"at": 0.0, "events": None}
_EVENTS_TTL = 120.0


def _wc_events() -> list[dict]:
    import time
    now = time.time()
    if _EVENTS_CACHE["events"] is not None and now - _EVENTS_CACHE["at"] < _EVENTS_TTL:
        return _EVENTS_CACHE["events"]
    events = (upcoming() or []) + (recent_results() or [])   # may raise → caller guards
    _EVENTS_CACHE.update(at=now, events=events)
    return events


def find_event_id(home: str, away: str, date) -> str | None:
    """Best-effort resolve a fixture to a SportsDB idEvent (the matches table doesn't
    store it). Scans the WC upcoming + recent feeds for a team-name + date match.
    Returns None when unavailable — the common case on the free key. Never raises."""
    try:
        d = date if isinstance(date, dt.date) else dt.date.fromisoformat(str(date))
    except ValueError:
        return None
    try:
        events = _wc_events()
    except Exception:
        return None
    h, a = home.lower(), away.lower()
    for e in events:
        eh = _canon(e.get("strHomeTeam")).lower()
        ea = _canon(e.get("strAwayTeam")).lower()
        try:
            ed = dt.date.fromisoformat(e.get("dateEvent") or "")
        except ValueError:
            continue
        # ±1 day: the feed's UTC date vs the schedule's local matchday
        if abs((ed - d).days) <= 1 and eh == h and ea == a:
            return e.get("idEvent")
    return None


def event_timeline(event_id: str) -> dict:
    """Goals/cards/subs for one event from TheSportsDB `lookuptimeline`, normalised to
    {events:[{minute, type, side, label, weight}], goals_home, goals_away}. Best-effort:
    the free key usually returns nothing, so callers must treat {} as 'no timeline'.
    Never raises."""
    if not event_id:
        return {}
    try:
        raw = (_get(f"lookuptimeline.php?id={event_id}") or {}).get("timeline") or []
    except Exception:
        return {}
    out = []
    gh = ga = 0
    for t in raw:
        side = "home" if (t.get("strHome") or "").lower() in ("yes", "home") else "away"
        kind = (t.get("strTimelineType") or t.get("strTimeline") or "").lower()
        minute = _to_int(t.get("intTime")) or 0
        weight = 1.0
        if "goal" in kind:
            weight = 1.0
            if side == "home":
                gh += 1
            else:
                ga += 1
        elif "card" in kind:
            weight = 0.2
        else:
            weight = 0.3
        out.append({"minute": minute, "type": kind or "event", "side": side,
                    "label": (t.get("strPlayer") or "").strip() or None,
                    "weight": weight})
    out.sort(key=lambda x: x["minute"])
    return {"events": out, "goals_home": gh, "goals_away": ga}


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
