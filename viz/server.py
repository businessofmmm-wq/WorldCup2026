#!/usr/bin/env python
"""
World Cup 2026 dashboard — pure-stdlib HTTP server.

No Flask, no framework: the project ethos is tiny-deps (requests + psycopg only),
so the dashboard rides on `http.server` from the standard library. It serves one
static page (viz/static) plus a small JSON API backed by the live engine —
Postgres ratings, the ensemble match predictor, the Monte-Carlo sim feeds and the
official 2026 bracket.

    python run.py viz                 # launch on http://localhost:8008
    python viz/server.py --port 8008  # same thing, run directly

Endpoints
    GET /api/meta        counts, accuracy, field, last-sim metadata
    GET /api/report      title odds + groups (data/sim_report.json)
    GET /api/groupadv    per-group advance odds (data/group_adv.json)
    GET /api/rankings    Elo power rankings from the DB
    GET /api/history     a team's Elo trajectory (downsampled)
    GET /api/predict     live ensemble prediction for any two teams
    GET /api/news        latest flagged headlines
    GET /api/bracket     official R32->Final wallchart with the model's chalk path
"""
from __future__ import annotations
import json
import os
import sys
import threading
import traceback
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Make the project root importable whether launched via run.py or directly.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config                                   # noqa: E402
import db                                        # noqa: E402
from models import field_2026                    # noqa: E402
from viz import flags as flagmod                 # noqa: E402

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DATA = config.DATA_DIR

# Held-out accuracy (see BACKTEST.md). Surfaced on the Method panel as proof the
# model is measured, not just plausible.
ACCURACY = {
    "rps": 0.1667, "logloss": 0.8565, "brier": 0.5037, "ece": 0.0112,
    "acc": 0.604, "n": 8009, "window": "2018+",
    "baseline_rps": 0.2267, "uniform_rps": 0.2394,
    "heldout_rps": 0.1650, "heldout_n": 3500, "heldout_window": "2023+",
}

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".json": "application/json",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
    ".woff2": "font/woff2", ".map": "application/json",
}

# Content-Security-Policy: a defense-in-depth backstop for the innerHTML-built
# UI. The dashboard renders RSS-derived text through an esc() barrier; this CSP
# is what stops anything that slips past (e.g. an injected inline event handler)
# from executing. 'unsafe-inline' is allowed for *styles* only (the hand-rolled
# UI uses inline style= throughout); scripts are pinned to same-origin, so inline
# event handlers won't run. Flags load from flagcdn; fonts are self-hosted
# same-origin (WOFF2 under /fonts/), so no third-party font origin is allowed.
CSP = (
    "default-src 'self'; "
    "img-src 'self' https://flagcdn.com data:; "
    "style-src 'self' 'unsafe-inline'; "
    "font-src 'self'; "
    "script-src 'self' https://cdnjs.cloudflare.com; "
    "connect-src 'self'; "
    "base-uri 'none'; "
    "frame-ancestors 'none'; "
    "object-src 'none'"
)

# --------------------------------------------------------------------------- #
# Lazy, shared, read-only engine handles (built once, reused across requests).
# --------------------------------------------------------------------------- #
_LOCK = threading.Lock()
_PREDICTOR = None
_BRACKET_CACHE = None
_PREDICT_CACHE: dict = {}  # (home, away, neutral) -> result; ratings static between refreshes


def predictor():
    """Build the ensemble Predictor once and share it (ratings are static between
    refreshes; predict() with log=False never writes, so it is safe to reuse)."""
    global _PREDICTOR
    if _PREDICTOR is None:
        with _LOCK:
            if _PREDICTOR is None:
                from models.predict import Predictor
                _PREDICTOR = Predictor()
    return _PREDICTOR


def _stars(elo: float) -> float:
    """Map an Elo rating to a 0.5–5 Panini-style star rating (half steps)."""
    raw = (elo - 1500.0) / 140.0
    return max(0.5, min(5.0, round(raw * 2) / 2))


def _team_card(team: str, elo: float | None = None) -> dict:
    p = predictor()
    e = p.elo.get(team, config.ELO_START) if elo is None else elo
    return {
        "team": team,
        "elo": round(e, 1),
        "stars": _stars(e),
        "flag": flagmod.flag_url(team),
        "iso2": flagmod.iso2(team),
        "confed": field_2026.CONFED_OF.get(team, "?"),
        "confed_color": flagmod.CONFED_COLOR.get(
            field_2026.CONFED_OF.get(team, "?"), flagmod.CONFED_COLOR["?"]),
    }


# --------------------------------------------------------------------------- #
# Endpoint implementations — each returns a JSON-able object.
# --------------------------------------------------------------------------- #
def ep_meta(_q) -> dict:
    h = {}
    try:
        h = db.health()
    except Exception:  # DB down — still serve what we can, without leaking details
        h = {"error": "database unavailable"}
    field = []
    for g, teams in field_2026.OFFICIAL_GROUPS.items():
        for t in teams:
            c = _team_card(t)
            c["group"] = g
            field.append(c)
    last_sim = None
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT created_at, runs FROM sim_results "
                "ORDER BY created_at DESC LIMIT 1").fetchone()
            if row:
                last_sim = {"at": row[0].isoformat(), "runs": row[1]}
    except Exception:
        pass
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "counts": {k: h.get(k) for k in (
            "matches", "finished_matches", "teams", "rated_teams",
            "news", "predictions")},
        "date_range": h.get("date_range"),
        "accuracy": ACCURACY,
        "hosts": field_2026.HOSTS,
        "host_flags": {t: flagmod.flag_url(t) for t in field_2026.HOSTS},
        "field": field,
        "last_sim": last_sim,
        "n_teams": len(field), "n_groups": len(field_2026.OFFICIAL_GROUPS),
        "n_matches_tournament": 104,
    }


def _read_json(name: str) -> dict:
    path = os.path.join(DATA, name)
    if not os.path.exists(path):
        return {"error": f"{name} not found — run `python run.py simulate`"}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def ep_report(_q):
    rep = _read_json("sim_report.json")
    # decorate each title-odds row with flag / confederation for the stickers
    for row in rep.get("title_odds", []):
        row.update({
            "flag": flagmod.flag_url(row["team"]),
            "iso2": flagmod.iso2(row["team"]),
            "confed": field_2026.CONFED_OF.get(row["team"], "?"),
            "confed_color": flagmod.CONFED_COLOR.get(
                field_2026.CONFED_OF.get(row["team"], "?"),
                flagmod.CONFED_COLOR["?"]),
        })
    return rep


def ep_groupadv(_q):
    adv = _read_json("group_adv.json")
    out = {}
    for g, rows in adv.items():
        out[g] = [{
            "team": t, "elo": e, "adv": a, "stars": _stars(e),
            "flag": flagmod.flag_url(t), "iso2": flagmod.iso2(t),
            "confed": field_2026.CONFED_OF.get(t, "?"),
            "confed_color": flagmod.CONFED_COLOR.get(
                field_2026.CONFED_OF.get(t, "?"), flagmod.CONFED_COLOR["?"]),
        } for (t, e, a) in rows]
    return out


def ep_rankings(q) -> dict:
    n = int((q.get("n", ["40"])[0]))
    n = max(1, min(n, 100))
    field_set = set(field_2026.FIELD)
    rows = []
    with db.connect() as conn:
        res = conn.execute(
            """
            SELECT team, elo, attack, defence, matches_count, last_match
            FROM team_ratings
            WHERE elo IS NOT NULL
              AND last_match >= (CURRENT_DATE - INTERVAL '4 years')
            ORDER BY elo DESC LIMIT %s
            """, (n,)).fetchall()
    for i, (team, elo, att, dfc, mc, last) in enumerate(res, 1):
        rows.append({
            "rank": i, "team": team, "elo": round(elo, 1),
            "attack": round(att, 3) if att is not None else None,
            "defence": round(dfc, 3) if dfc is not None else None,
            "matches": mc, "last_match": last.isoformat() if last else None,
            "stars": _stars(elo), "in_field": team in field_set,
            "flag": flagmod.flag_url(team), "iso2": flagmod.iso2(team),
            "confed": field_2026.CONFED_OF.get(team, "?"),
            "confed_color": flagmod.CONFED_COLOR.get(
                field_2026.CONFED_OF.get(team, "?"), flagmod.CONFED_COLOR["?"]),
        })
    return {"rankings": rows}


def ep_history(q) -> dict:
    team = q.get("team", [None])[0]
    if not team:
        return {"error": "team required"}
    points = int(q.get("points", ["140"])[0])
    with db.connect() as conn:
        res = conn.execute(
            "SELECT match_date, elo FROM elo_history WHERE team=%s "
            "ORDER BY match_date", (team,)).fetchall()
    series = [(d.isoformat(), round(e, 1)) for d, e in res]
    # downsample evenly to keep payloads light, but always keep the last point
    if len(series) > points:
        step = len(series) / points
        idx = sorted({int(i * step) for i in range(points)} | {len(series) - 1})
        series = [series[i] for i in idx]
    peak = max((e for _, e in series), default=None)
    return {"team": team, "flag": flagmod.flag_url(team),
            "series": series, "peak": peak,
            "current": series[-1][1] if series else None,
            "n": len(res)}


def ep_predict(q) -> dict:
    home = q.get("home", [None])[0]
    away = q.get("away", [None])[0]
    if not home or not away:
        return {"error": "home and away required"}
    neutral = q.get("neutral", ["1"])[0] not in ("0", "false", "no")
    ck = (home, away, neutral)
    hit = _PREDICT_CACHE.get(ck)
    if hit is not None:
        return hit
    p = predictor()
    r = p.predict(home, away, neutral=neutral, log=False)
    grid, lh, la = p.goals.scoreline_grid(home, away, neutral=neutral)
    # top few likely scorelines for the tale-of-the-tape
    flat = sorted(
        ((grid[i][j], i, j) for i in range(len(grid)) for j in range(len(grid))),
        reverse=True)[:6]
    r["top_scorelines"] = [{"score": f"{i}-{j}", "p": prob} for prob, i, j in flat]
    r["home_card"] = _team_card(home, r["elo_home"])
    r["away_card"] = _team_card(away, r["elo_away"])
    _PREDICT_CACHE[ck] = r
    return r


def ep_news(q) -> dict:
    team = q.get("team", [None])[0]
    n = int(q.get("n", ["30"])[0])
    n = max(1, min(n, 80))
    from sources import news as src_news
    out = []
    for row in src_news.recent(n, team=team):
        if team:
            pub, src, title, fl = row
            teams = [team]
        else:
            pub, src, title, fl, teams = row
        out.append({
            "published": pub.isoformat() if pub else None,
            "source": src, "title": title,
            "flags": list(fl or []), "teams": list(teams or []),
            "team_flags": {t: flagmod.flag_url(t) for t in (teams or [])
                           if flagmod.flag_url(t)},
        })
    return {"news": out, "team": team}


def _build_bracket() -> dict:
    """Compute the official R32->Final wallchart and the model's 'chalk' path
    (the higher pairwise win-prob team advances at every tie). Cached per run."""
    global _BRACKET_CACHE
    if _BRACKET_CACHE is not None:
        return _BRACKET_CACHE

    adv = _read_json("group_adv.json")
    report = _read_json("sim_report.json")
    pwin = {r["team"]: r.get("p_win", 0.0) for r in report.get("title_odds", [])}
    elo_of = {}
    proj = {}  # slot -> team
    for g, rows in adv.items():           # rows already Elo-sorted in the file
        names = [t for (t, _e, _a) in rows]
        for (t, e, _a) in rows:
            elo_of[t] = e
        proj["1" + g] = names[0]
        proj["2" + g] = names[1]

    # Fill the eight 3rd-place slots: best available 3rd (by Elo) among the
    # groups each slot is allowed to draw from (FIFA Annex C ranges).
    thirds = {g: rows[2][0] for g, rows in adv.items()}
    used = set()
    for slot in sorted(field_2026.ALLOWED_THIRDS,
                       key=lambda s: len(field_2026.ALLOWED_THIRDS[s])):
        cands = [g for g in field_2026.ALLOWED_THIRDS[slot] if g in thirds
                 and g not in used]
        if not cands:
            cands = [g for g in thirds if g not in used]
        best = max(cands, key=lambda g: elo_of.get(thirds[g], 0))
        used.add(best)
        proj[slot] = thirds[best]
        proj_meta_src = proj.setdefault("_third_src", {})
        proj_meta_src[slot] = best

    p = predictor()

    def beats(a: str, b: str) -> str:
        pr = p.predict(a, b, neutral=True, log=False)
        return a if pr["p_home"] >= pr["p_away"] else b

    def card(team: str) -> dict:
        return {"team": team, "flag": flagmod.flag_url(team),
                "iso2": flagmod.iso2(team),
                "elo": round(elo_of.get(team, p.elo.get(team, config.ELO_START))),
                "p_win": pwin.get(team, 0.0),
                "confed": field_2026.CONFED_OF.get(team, "?")}

    r32 = []
    results = {}
    for m, s1, s2 in field_2026.R32:
        a, b = proj[s1], proj[s2]
        w = beats(a, b)
        results[m] = w
        r32.append({"match": m, "slot1": s1, "slot2": s2,
                    "a": card(a), "b": card(b), "winner": w})

    rounds = {"r16": [], "qf": [], "sf": [], "final": []}
    stage_of = {**{m: "r16" for m in range(89, 97)},
                **{m: "qf" for m in range(97, 101)},
                101: "sf", 102: "sf", 104: "final"}
    for m in (89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104):
        s1, s2 = field_2026.BRACKET[m]
        a, b = results[s1], results[s2]
        w = beats(a, b)
        results[m] = w
        rounds[stage_of[m]].append(
            {"match": m, "a": card(a), "b": card(b), "winner": w})

    _BRACKET_CACHE = {
        "r32": r32, "rounds": rounds,
        "champion": card(results[104]),
        "third_src": proj.get("_third_src", {}),
        "note": "Slots 1X/2X = projected group winners/runners by Elo; T## = best "
                "available 3rd by Elo within FIFA Annex C ranges. The highlighted "
                "path advances the higher pairwise win-probability side each tie.",
    }
    return _BRACKET_CACHE


def ep_bracket(_q):
    return _build_bracket()


# The tournament window — used to scope the Match Centre to WC 2026 fixtures.
from models import schedule_2026               # noqa: E402
WC_START = dt.date(2026, 6, 11)


def _outcome(hs: int, as_: int) -> str:
    return "home" if hs > as_ else "away" if as_ > hs else "draw"


def _kickoff_utc(home: str, away: str) -> dt.datetime | None:
    iso = schedule_2026.KICKOFFS_UTC.get((home, away))
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")) if iso else None


def log_upcoming_calls(horizon_hours: int = 36) -> int:
    """Freeze the model's pre-match call for every WC fixture kicking off within
    `horizon_hours` (the hourly export keeps these fresh). ep_fixtures then
    grades completed matches against the *stored* pre-kickoff call rather than a
    prediction recomputed from ratings that have already absorbed the result —
    the difference between an honest record and a hindsight-flattered one."""
    p = predictor()
    now = dt.datetime.now(dt.timezone.utc)
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT match_date, home_team, away_team FROM matches "
            "WHERE tournament='FIFA World Cup' AND match_date >= %s "
            "AND home_score IS NULL ORDER BY match_date, id",
            (now.date() - dt.timedelta(days=1),)).fetchall()
    n = 0
    for d, h, a in rows:
        ko = _kickoff_utc(h, a) or dt.datetime.combine(
            d, dt.time(12), tzinfo=dt.timezone.utc)
        if now - dt.timedelta(hours=3) <= ko <= now + dt.timedelta(hours=horizon_hours):
            try:
                p.predict(h, a, neutral=True, log=True, match_date=d)
                n += 1
            except Exception:
                pass                        # one bad fixture never blocks the rest
    return n


def _frozen_calls(conn) -> dict:
    """Latest stored pre-kickoff prediction per WC fixture, keyed (home, away).
    Predictions are only logged while a fixture is unplayed, so every row
    predates the result reaching the model; the kickoff cutoff (when known)
    additionally drops anything logged in-play."""
    rows = conn.execute(
        "SELECT home_team, away_team, created_at, p_home, p_draw, p_away, "
        "       exp_home_goals, exp_away_goals, top_scoreline "
        "FROM predictions WHERE match_date >= %s ORDER BY created_at",
        (WC_START,)).fetchall()
    out: dict = {}
    for h, a, created, ph, pd_, pa, xh, xa, ts in rows:
        ko = _kickoff_utc(h, a)
        if ko is not None and created is not None and created > ko:
            continue
        out[(h, a)] = {"p_home": ph, "p_draw": pd_, "p_away": pa,
                       "exp_home_goals": xh, "exp_away_goals": xa,
                       "top_scoreline": ts}
    return out


def ep_fixtures(q) -> dict:
    """Match Centre: every WC 2026 fixture with the model's call. Upcoming ties
    carry a live ensemble prediction; completed ties carry the real score plus
    whether the model called the result (a running scoreboard during the cup) —
    graded against the prediction *frozen before kickoff* whenever one exists.

    The reliable "not yet played" signal is a NULL score — the imported schedule
    tags future fixtures inconsistently in `status`, so we key off the score.
    """
    p = predictor()
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT match_date, home_team, away_team, home_score, away_score,
                   neutral, city, country
            FROM matches
            WHERE tournament = 'FIFA World Cup' AND match_date >= %s
            ORDER BY match_date, id
            """, (WC_START,)).fetchall()
        frozen = _frozen_calls(conn)

    upcoming, completed = [], []
    played = called = 0
    for (d, home, away, hs, as_, neutral, city, country) in rows:
        neutral = bool(neutral)
        pr = p.predict(home, away, neutral=neutral, log=False)
        done = hs is not None and as_ is not None
        # Completed ties are shown + graded on the frozen pre-kickoff call when
        # one was stored; the live recompute is only the (pre-tournament) fallback.
        fz = frozen.get((home, away)) if done else None
        view = {**pr, **fz} if fz else pr
        fav = max(("home", view["p_home"]), ("draw", view["p_draw"]),
                  ("away", view["p_away"]), key=lambda kv: kv[1])[0]
        base = {
            "date": d.isoformat(),
            "home": _team_card(home, pr["elo_home"]),
            "away": _team_card(away, pr["elo_away"]),
            "neutral": neutral, "venue": (city or "") + (", " + country if country else ""),
            "p_home": view["p_home"], "p_draw": view["p_draw"], "p_away": view["p_away"],
            "fav": fav, "exp_home_goals": view["exp_home_goals"],
            "exp_away_goals": view["exp_away_goals"], "top_scoreline": view["top_scoreline"],
            "kickoff": schedule_2026.KICKOFFS_UTC.get((home, away)),
        }
        if not done:                            # not played yet
            upcoming.append(base)
        else:
            actual = _outcome(hs, as_)
            ok = (actual == fav)
            played += 1
            called += int(ok)
            base.update({"home_score": hs, "away_score": as_,
                         "actual": actual, "called": ok,
                         "frozen_call": bool(fz)})
            completed.append(base)

    completed.reverse()                          # most-recent result first
    return {
        "kickoff": WC_START.isoformat(),
        "upcoming": upcoming,
        "completed": completed,
        "record": {"played": played, "called": called,
                   "pct": round(called / played, 3) if played else None},
        "note": "Upcoming ties show the live ensemble call (win/draw/win, xG, "
                "likeliest score). Completed ties show the real result and whether "
                "the model called the outcome.",
    }


# --------------------------------------------------------------------------- #
# Quantum Tactics Lab — superposition projection (always), plus a CV board and a
# collapse overlay when those are locally available. No CV runs here: the heavy
# pipeline (tools/cv_tactics.py) is build-time only and writes data/tactics/<key>.json;
# this endpoint only *reads* that JSON if it exists.
# --------------------------------------------------------------------------- #
TACTICS_DIR = os.path.join(DATA, "tactics")


def _tactics_fixtures() -> list[dict]:
    """One lightweight pass over the WC fixtures, keyed for the Lab. Reuses ep_fixtures
    so kickoff/score/venue logic stays in one place."""
    from models import tactics
    fx = ep_fixtures({})
    out = []
    for status, rows in (("upcoming", fx.get("upcoming", [])),
                         ("completed", fx.get("completed", []))):
        for r in rows:
            home, away = r["home"]["team"], r["away"]["team"]
            key = tactics.match_key(home, away, r["date"])
            out.append({
                "key": key, "home": home, "away": away, "date": r["date"],
                "neutral": r.get("neutral", True), "kickoff": r.get("kickoff"),
                "status": status,
                "home_score": r.get("home_score"), "away_score": r.get("away_score"),
            })
    return out


def _cv_packet(key: str) -> dict | None:
    path = os.path.join(TACTICS_DIR, f"{key}.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return None


def ep_tactics_index(_q) -> dict:
    """List analysable matches: every 2026 fixture, plus any local CV showcase whose key
    isn't a scheduled fixture. Each entry flags whether a CV board / timeline exists."""
    fixtures = _tactics_fixtures()
    keys = {f["key"] for f in fixtures}
    items = []
    for f in fixtures:
        items.append({
            "key": f["key"], "home": f["home"], "away": f["away"],
            "date": f["date"], "kickoff": f["kickoff"], "status": f["status"],
            "home_card": _team_card(f["home"]), "away_card": _team_card(f["away"]),
            "has_cv": _cv_packet(f["key"]) is not None,
        })
    # curated CV showcases that aren't on the schedule
    if os.path.isdir(TACTICS_DIR):
        for name in sorted(os.listdir(TACTICS_DIR)):
            if not name.endswith(".json"):
                continue
            k = name[:-5]
            if k in keys:
                continue
            cv = _cv_packet(k) or {}
            items.append({"key": k, "home": cv.get("home_name", k), "away": cv.get("away_name", ""),
                          "date": None, "kickoff": None, "status": "showcase",
                          "has_cv": True})
    return {"matches": items, "n": len(items),
            "note": "Every fixture carries the model's pre-match superposition. A CV "
                    "board appears for matches analysed locally from rights-cleared "
                    "footage; a collapse overlay appears once a result is in."}


def ep_tactics(q) -> dict:
    """The full tactical packet for one match key: the model superposition (always),
    a CV board if present, a live timeline if available, and a collapse overlay once
    the fixture is finished."""
    from models import tactics
    key = q.get("match", [None])[0]
    if not key:
        return {"error": "match key required (?match=<key>)"}

    fixtures = {f["key"]: f for f in _tactics_fixtures()}
    fx = fixtures.get(key)
    cv = _cv_packet(key)

    if fx is None and cv is None:
        return {"error": f"unknown match key: {key}"}

    if fx is not None:
        home, away, neutral = fx["home"], fx["away"], fx["neutral"]
    else:                                            # CV-only showcase
        home = cv.get("home_name") or "Home"
        away = cv.get("away_name") or "Away"
        neutral = True

    packet = tactics.project(predictor(), home, away, neutral=neutral)
    packet["key"] = key
    packet["home_card"] = _team_card(home, packet["elo"]["home"])
    packet["away_card"] = _team_card(away, packet["elo"]["away"])
    packet["cv"] = cv                                 # may be None — front-end degrades

    if fx is not None:
        packet["date"] = fx["date"]
        packet["kickoff"] = fx["kickoff"]
        packet["status"] = fx["status"]
        if fx.get("home_score") is not None and fx.get("away_score") is not None:
            timeline = []
            try:                                      # best-effort live timeline
                from sources import sportsdb
                eid = sportsdb.find_event_id(home, away, fx["date"])
                tl = sportsdb.event_timeline(eid) if eid else {}
                timeline = tl.get("events", []) if tl else []
            except Exception:
                timeline = []
            packet = tactics.collapse(
                packet, real_score=(fx["home_score"], fx["away_score"]),
                timeline=timeline)
            packet["has_timeline"] = bool(timeline)
    return packet


ROUTES = {
    "/api/meta": ep_meta, "/api/report": ep_report, "/api/groupadv": ep_groupadv,
    "/api/rankings": ep_rankings, "/api/history": ep_history,
    "/api/predict": ep_predict, "/api/news": ep_news, "/api/bracket": ep_bracket,
    "/api/fixtures": ep_fixtures,
    "/api/tactics_index": ep_tactics_index, "/api/tactics": ep_tactics,
}


class Handler(BaseHTTPRequestHandler):
    server_version = "WC26Viz/1.0"

    def log_message(self, fmt, *args):   # quieter console
        return

    def _send(self, code, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        # Serve `/api/<name>.json` as an alias for `/api/<name>` so the front-end
        # uses one set of URLs on both the live server and the static CDN build
        # (where the snapshots are literally `<name>.json` files). No host-specific
        # redirect rules needed.
        route = path
        if route not in ROUTES and route.endswith(".json") and route[:-5] in ROUTES:
            route = route[:-5]
        if route in ROUTES:
            try:
                q = parse_qs(parsed.query)
                self._json(ROUTES[route](q))
            except Exception:
                # Log server-side only; don't leak internals (DB errors, file
                # paths, the DSN) to the client.
                traceback.print_exc()
                self._json({"error": "internal server error",
                            "hint": "check the server logs; is PostgreSQL running? "
                                    "try `python run.py health`"},
                           code=500)
            return
        self._serve_static(path)

    def _serve_static(self, path: str):
        if path in ("/", "/index.html"):
            rel = "index.html"
        elif path == "/graph":          # convenience alias for the architecture page
            rel = "graph.html"
        else:
            rel = path.lstrip("/")
        # Resolve against the static root and confirm the *real* path stays
        # inside it. The os.sep boundary defeats the `static`/`static-evil`
        # prefix trick; realpath() also blocks symlink escapes.
        root = os.path.realpath(STATIC)
        full = os.path.realpath(os.path.join(root, rel))
        if (full != root and not full.startswith(root + os.sep)) \
                or not os.path.isfile(full):
            self._send(404, b"404 not found", "text/plain; charset=utf-8")
            return
        ext = os.path.splitext(full)[1].lower()
        with open(full, "rb") as fh:
            body = fh.read()
        self._send(200, body, CONTENT_TYPES.get(ext, "application/octet-stream"))


def serve(port: int = 8008, host: str = "127.0.0.1"):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://localhost:{port}"
    print("=" * 60)
    print("  WORLD CUP 2026  —  PREDICTION ALBUM  (retro-terrace dashboard)")
    print("=" * 60)
    print(f"  serving on {url}")
    print("  Ctrl+C to stop")
    print("=" * 60)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped.")
        httpd.server_close()


if __name__ == "__main__":
    port = 8008
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        if i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    serve(port=port)
