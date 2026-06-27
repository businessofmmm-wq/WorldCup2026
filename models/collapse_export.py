#!/usr/bin/env python
"""
Collapse export — static data for the WCPA "Collapse" run game (Quantum Tactics Lab v2).

The game runs entirely client-side: viz/static/collapse-core.js rebuilds the
bivariate-Poisson scoreline grid for any fixture from the per-pair expected-goals
means + the global shared covariance lambda3, applies the player's quantum operators,
and resolves a single-team run deterministically from a seed. This module emits the
two static inputs that core needs:

    api/collapse.json   live snapshot — every ordered-pair expected goals, lambda3,
                        per-team display data and the bracket wiring. Free-play mode
                        reads this; it tracks the hourly re-export.
    api/daily.json      the daily challenge — a date-stamped, FROZEN copy of the same
                        snapshot plus a date-derived seed. Written once per UTC day
                        (idempotent across the hourly redeploys) so every player AND
                        the server-side verifier (functions/api/run/submit) resolve the
                        same timeline against identical data. Only daily runs are
                        leaderboard-eligible — that frozen snapshot is what makes the
                        replay verification exact.

Base-grid parity: the means come straight from p.goals.expected_goals(), the exact
value models/bivpoisson.scoreline_grid() uses, so a no-operator run reproduces the
engine's scoreline superposition cell-for-cell. (The game deliberately works at the
goals-grid level — like the tournament sim's _sample_score — not the Elo+goals
ensemble, so operators move one coherent distribution that drives every outcome,
including knockout shootouts.)
"""
from __future__ import annotations
import hashlib
import json
import os
import datetime as dt

import config
from models import field_2026
from models import tactics
from viz import flags


def _write_json(path: str, obj) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def build_collapse_data(p) -> dict:
    """Assemble the client/verifier snapshot from a built Predictor `p`.

    eg[home][away] = [mean_home, mean_away] for every ordered pair over the 48-team
    field, neutral venue (every World Cup match is neutral in the sim). The client
    derives l3 = min(lambda3, mean_h-eps, mean_a-eps), l1 = mean_h-l3, l2 = mean_a-l3
    and the grid exactly as models/bivpoisson.scoreline_grid does — so the means are
    kept at high precision to make that round-trip essentially lossless.
    """
    field = sorted(field_2026.FIELD)

    eg: dict[str, dict[str, list[float]]] = {}
    for home in field:
        row: dict[str, list[float]] = {}
        for away in field:
            if home == away:
                continue
            mh, ma = p.goals.expected_goals(home, away, neutral=True)
            row[away] = [round(float(mh), 6), round(float(ma), 6)]
        eg[home] = row

    teams: dict[str, dict] = {}
    for t in field:
        teams[t] = {
            "elo": round(float(p.elo.get(t, config.ELO_START)), 1),
            "confed": field_2026.CONFED_OF.get(t, "?"),
            "iso2": flags.iso2(t),
            "fingerprint": tactics._fingerprint(p, t),
        }

    # Bracket wiring (JSON-safe: int keys -> str, sets -> sorted lists, tuples -> lists)
    bracket = {
        "groups": field_2026.OFFICIAL_GROUPS,
        "r32": [list(m) for m in field_2026.R32],
        "allowed_thirds": {k: sorted(v) for k, v in field_2026.ALLOWED_THIRDS.items()},
        "bracket": {str(k): list(v) for k, v in field_2026.BRACKET.items()},
        "winner_stage": {str(k): v for k, v in field_2026.WINNER_STAGE.items()},
        "hosts": list(field_2026.HOSTS),
    }

    return {
        "lambda3": round(float(getattr(p.goals, "lam3", 0.0) or 0.0), 6),
        "mu": round(float(getattr(p.goals, "mu", 0.0)), 6),
        "gamma": round(float(getattr(p.goals, "gamma", 0.0)), 6),
        "goals_model": config.GOALS_MODEL,
        "max_goals": config.DC_MAX_GOALS,
        "field": field,
        "teams": teams,
        "eg": eg,
        "bracket": bracket,
    }


def export_collapse(api_dir: str, p) -> None:
    """Write the live snapshot api/collapse.json (free-play mode + base data)."""
    data = build_collapse_data(p)
    kb = _write_json(os.path.join(api_dir, "collapse.json"), data) / 1024
    print(f"  api/collapse.json  ({len(data['eg'])} teams, {kb:.0f} KB)")


def daily_seed(date_iso: str) -> int:
    """Deterministic uint32 seed for a date. Derived from the date (not secret — the
    anti-cheat is the server-side replay, not seed secrecy), so the daily timeline is
    auditable: anyone can confirm the seed matches the date."""
    return int(hashlib.sha256(date_iso.encode()).hexdigest()[:8], 16)


def export_daily(api_dir: str, p) -> None:
    """Write api/daily.json — the frozen daily-challenge snapshot. Idempotent per UTC
    day: if today's file already exists it is kept untouched, so the hourly redeploys
    never reshuffle a challenge mid-day and the verifier stays in lock-step with what
    players actually played."""
    path = os.path.join(api_dir, "daily.json")
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    try:
        with open(path, encoding="utf-8") as fh:
            if json.load(fh).get("date") == today:
                print(f"  api/daily.json  (frozen for {today}, kept)")
                return
    except (FileNotFoundError, ValueError):
        pass
    seed = daily_seed(today)
    data = {"date": today, "seed": seed, "snapshot": build_collapse_data(p)}
    kb = _write_json(path, data) / 1024
    print(f"  api/daily.json  (new challenge {today}, seed {seed}, {kb:.0f} KB)")


# --------------------------------------------------------------------------- #
# Self-check — confirm the exported means + lambda3 round-trip to the engine's
# scoreline_grid (the base-grid parity guarantee), runnable standalone.
# --------------------------------------------------------------------------- #
def _selfcheck(p, data: dict, pairs=(("Brazil", "Haiti"), ("Spain", "Germany"),
                                     ("Argentina", "Algeria"))) -> None:
    import math

    def bp_pmf(x, y, l1, l2, l3):
        l1 = max(l1, 1e-9); l2 = max(l2, 1e-9)
        if l3 > 0.0:
            ratio = l3 / (l1 * l2)
            s = sum(math.comb(x, k) * math.comb(y, k) * math.factorial(k) * ratio ** k
                    for k in range(min(x, y) + 1))
        else:
            s = 1.0
        return math.exp(-(l1 + l2 + l3) + x * math.log(l1) - math.lgamma(x + 1)
                        + y * math.log(l2) - math.lgamma(y + 1) + math.log(s))

    lam3 = data["lambda3"]
    mg = data["max_goals"]
    worst = 0.0
    for home, away in pairs:
        mh, ma = data["eg"][home][away]
        l3 = min(lam3, mh - 1e-6, ma - 1e-6)
        l3 = l3 if l3 > 0.0 else 0.0
        l1, l2 = mh - l3, ma - l3
        grid = [[bp_pmf(i, j, l1, l2, l3) for j in range(mg + 1)] for i in range(mg + 1)]
        tot = sum(sum(r) for r in grid)
        grid = [[c / tot for c in r] for r in grid]
        ref, _, _ = p.goals.scoreline_grid(home, away, neutral=True)
        d = max(abs(grid[i][j] - ref[i][j]) for i in range(mg + 1) for j in range(mg + 1))
        worst = max(worst, d)
        print(f"    parity {home[:8]:>8} vs {away[:8]:<8}  max abs cell diff = {d:.2e}")
    status = "OK" if worst < 1e-5 else "DRIFT"
    print(f"  base-grid parity: {status} (worst {worst:.2e} across {len(pairs)} pairs)")


if __name__ == "__main__":
    import sys
    from viz import server

    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(config.ROOT, "dist", "api")
    os.makedirs(out, exist_ok=True)
    pred = server.predictor()
    data = build_collapse_data(pred)
    export_collapse(out, pred)
    export_daily(out, pred)
    _selfcheck(pred, data)
