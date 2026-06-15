"""
Live fixtures + results via football-data.org v4 (competition code `WC`).

Drop-in replacement for the live-results inflow previously served by
`sources/sportsdb.py` (TheSportsDB free key "3"). It writes new/updated World Cup
scores into `matches` with source 'footballdata' so the next train run folds the
finished results into the ratings — same contract as the old feed.

Why this feed beats the alternatives for WC2026:
  - explicit per-match `status` (SCHEDULED -> TIMED -> IN_PLAY -> PAUSED -> FINISHED)
    and an ISO `utcDate`, so "is it live / is it final" is unambiguous;
  - reliable full-time scores;
  - 10 requests/min on the free tier — we poll every 5 min, far inside the limit
    (API-Football's free 100 req/day is too low for 5-min polling; Sportradar/Opta
    are paid). See the ingest diagram in chat.

What this does NOT change: martj42 history (sources/results.py) and StatsBomb xG
(sources/statsbomb.py) are untouched, and viz/server.py keeps calling
sources/sportsdb.py for its best-effort goal timelines. This module replaces only
the live score inflow.

Auth: free token from https://www.football-data.org/client/register, exposed as
env var / CI secret WCPA_FOOTBALLDATA_TOKEN. (Optionally mirror it into config.py
as FOOTBALLDATA_TOKEN; this module reads config first, then the env var.)
"""
from __future__ import annotations
import datetime as dt
import os
import time

import requests

import config
from db import connect

API_BASE = "https://api.football-data.org/v4"
COMPETITION = "WC"  # FIFA World Cup
TOURNAMENT = "FIFA World Cup"  # stored in matches.tournament (triggers field check)

# football-data.org status -> matches.status. FINISHED is the only state we treat
# as a real result the model may train on; IN_PLAY/PAUSED are stored as 'live'
# (model trains on status='finished' only, so a half-played game can't leak in).
_FINAL = {"FINISHED"}
_LIVE = {"IN_PLAY", "PAUSED"}


def _token() -> str:
    tok = (getattr(config, "FOOTBALLDATA_TOKEN", None)
           or os.environ.get("WCPA_FOOTBALLDATA_TOKEN", "")).strip()
    if not tok:
        raise RuntimeError(
            "WCPA_FOOTBALLDATA_TOKEN is not set. Get a free token at "
            "https://www.football-data.org/client/register, add it as a repo "
            "secret, and (for local runs) put it in your .env."
        )
    return tok


# football-data national-team spellings -> the engine's canonical names
# (martj42 conventions, same target set as sportsdb.NAME_MAP). Storing a variant
# would silently fork a phantom team and the result would never reach the model.
# Verify against the live feed on a matchday — the field-membership warning below
# prints any name that isn't one of the 48, so unmapped spellings surface loudly.
NAME_MAP = {
    "USA": "United States", "United States of America": "United States",
    "Korea Republic": "South Korea", "Korea DPR": "North Korea",
    "IR Iran": "Iran",
    "Cote d'Ivoire": "Ivory Coast", "Côte d'Ivoire": "Ivory Coast",
    "Turkiye": "Turkey", "Türkiye": "Turkey",
    "Czechia": "Czech Republic",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "Cabo Verde": "Cape Verde",
    "Congo DR": "DR Congo", "DR Congo": "DR Congo",
    "Curacao": "Curaçao",
}


def _canon(name: str | None) -> str:
    name = (name or "").strip()
    return NAME_MAP.get(name, name)


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _get(path: str, *, retries: int = 2, backoff: float = 2.0) -> dict:
    """GET an API path with the auth header. One retry with backoff on 429/5xx so a
    single rate blip doesn't fail the whole run."""
    url = f"{API_BASE}/{path}"
    headers = {"X-Auth-Token": _token(), "User-Agent": "WorldCup2026-Predictor/1.0"}
    for attempt in range(retries + 1):
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
            time.sleep(backoff * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json() or {}
    resp.raise_for_status()
    return {}


def matches(status: tuple[str, ...] | None = None) -> list[dict]:
    """Raw WC match objects, optionally filtered by feed status to keep payloads
    small. status=("IN_PLAY","PAUSED","FINISHED") is the live-poll set."""
    path = f"competitions/{COMPETITION}/matches"
    if status:
        path += "?status=" + ",".join(status)
    return (_get(path) or {}).get("matches") or []


def _store(events: list[dict]) -> dict:
    """Upsert WC matches into `matches`. Mirrors the sportsdb defensive write path:

    - match_date is the UTC calendar day; an existing scheduled row within ±1 day
      claims the event (the imported schedule's local-matchday date stays canonical),
      so a 01:00Z kickoff doesn't duplicate the fixture;
    - a real score is never overwritten with NULL (guards a flaky in-play payload);
    - status: FINISHED -> 'finished', IN_PLAY/PAUSED -> 'live', else 'scheduled'.
    """
    from models import field_2026
    n_final = n_live = n_sched = 0
    with connect() as conn:
        for e in events:
            home = _canon((e.get("homeTeam") or {}).get("name"))
            away = _canon((e.get("awayTeam") or {}).get("name"))
            utc = e.get("utcDate")
            if not (home and away and utc):
                continue
            try:
                d = dt.datetime.fromisoformat(utc.replace("Z", "+00:00")).date()
            except ValueError:
                continue
            ft = (e.get("score") or {}).get("fullTime") or {}
            hs, as_ = _to_int(ft.get("home")), _to_int(ft.get("away"))
            feed_status = (e.get("status") or "").upper()
            if feed_status in _FINAL:
                status = "finished"
            elif feed_status in _LIVE:
                status = "live"
            else:
                status = "scheduled"
                hs = as_ = None  # ignore any placeholder score on an unstarted game

            for t in (home, away):
                if t not in field_2026.FIELD:
                    print(f"  ! footballdata name not in the 48-team field: {t!r} "
                          f"({home} v {away} {d}) — add it to NAME_MAP")

            row = conn.execute(
                """
                SELECT id, home_score, away_score, status FROM matches
                WHERE home_team=%s AND away_team=%s AND tournament=%s
                  AND match_date BETWEEN %s AND %s
                ORDER BY abs(match_date - %s) LIMIT 1
                """,
                (home, away, TOURNAMENT,
                 d - dt.timedelta(days=1), d + dt.timedelta(days=1), d),
            ).fetchone()

            if row:
                mid, old_hs, old_as, _old_status = row
                if hs is None and old_hs is not None:
                    continue  # flaky regression — keep the existing result
                if (hs, as_) == (old_hs, old_as):
                    # scores unchanged; still let status advance (e.g. live->finished)
                    conn.execute("UPDATE matches SET status=%s WHERE id=%s",
                                 (status, mid))
                else:
                    conn.execute(
                        "UPDATE matches SET home_score=%s, away_score=%s, status=%s "
                        "WHERE id=%s", (hs, as_, status, mid))
            else:
                conn.execute(
                    """
                    INSERT INTO matches
                        (match_date, home_team, away_team, home_score, away_score,
                         tournament, neutral, source, status)
                    VALUES (%s,%s,%s,%s,%s,%s,TRUE,'footballdata',%s)
                    """,
                    (d, home, away, hs, as_, TOURNAMENT, status))

            if status == "finished":
                n_final += 1
            elif status == "live":
                n_live += 1
            else:
                n_sched += 1
    return {"finished": n_final, "live": n_live, "scheduled": n_sched}


def ingest(verbose: bool = True) -> dict:
    """Live inflow entry point — drop-in for sportsdb.ingest(). Pulls in-play,
    paused and finished WC matches and upserts them. Never lets a feed outage kill
    the run (returns zeros and prints the reason instead)."""
    try:
        evs = matches(status=("IN_PLAY", "PAUSED", "FINISHED"))
    except Exception as exc:
        if verbose:
            print(f"  live feed skipped: {exc}")
        return {"finished": 0, "live": 0, "scheduled": 0}
    out = _store(evs)
    if verbose:
        print(f"  live feed: {out['finished']} finished, {out['live']} live, "
              f"{out['scheduled']} scheduled stored")
    return out


def event_timeline_by_match(match_id: int) -> dict:
    """Optional richer timeline straight from football-data: goal minute + scorer +
    assist + side for one match (the competition list omits goals; the per-match
    detail includes them). Normalised like sportsdb.event_timeline so viz/server.py
    could switch to it later. Best-effort: returns {} on any failure."""
    try:
        m = _get(f"matches/{match_id}")
    except Exception:
        return {}
    home_name = ((m.get("homeTeam") or {}).get("name"))
    out, gh, ga = [], 0, 0
    for g in (m.get("goals") or []):
        side = "home" if (g.get("team") or {}).get("name") == home_name else "away"
        if side == "home":
            gh += 1
        else:
            ga += 1
        out.append({
            "minute": _to_int(g.get("minute")) or 0,
            "type": (g.get("type") or "goal").lower(),
            "side": side,
            "label": (g.get("scorer") or {}).get("name"),
            "assist": (g.get("assist") or {}).get("name"),
            "weight": 1.0,
        })
    out.sort(key=lambda x: x["minute"])
    return {"events": out, "goals_home": gh, "goals_away": ga}


if __name__ == "__main__":
    # Smoke test: prints what the live poll would ingest. Needs the token in env.
    print(ingest())
    print("\n  Live / finished WC matches right now:")
    for e in matches(status=("IN_PLAY", "PAUSED", "FINISHED"))[:12]:
        ft = (e.get("score") or {}).get("fullTime") or {}
        print(f"   {e.get('utcDate')} {(e.get('homeTeam') or {}).get('name')} "
              f"{ft.get('home')}-{ft.get('away')} "
              f"{(e.get('awayTeam') or {}).get('name')} [{e.get('status')}]")
