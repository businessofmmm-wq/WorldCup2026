"""
Quantum Tactics — the analytical engine behind the WCPA "Quantum Tactics Lab".

The lens (Samuel's framing, kept faithful): a fixture is held in *superposition* —
the joint scoreline grid is the amplitude distribution over every possible result,
and the bivariate-Poisson shared term lambda3 is the *entanglement* coupling the two
teams' goal counts (the part independent Poissons miss). Kick-off "collapses" that
superposition into one observed score; this module produces both the pre-match
superposition and, once a result lands, the collapse overlay.

Pure-Python, read-only. `project()` takes an already-built `Predictor` (the caller
owns the cached singleton — viz.server.predictor()), so this module never imports the
server and there is no import cycle. No model fitting happens here.

    from models.predict import Predictor
    from models.tactics import match_key, project, collapse
    p = Predictor()
    pkt = project(p, "Brazil", "Morocco", neutral=True)        # pre-match
    pkt = collapse(pkt, real_score=(2, 1), timeline=[...])     # post-match overlay
"""
from __future__ import annotations
import math
import re

import config


def match_key(home: str, away: str, date) -> str:
    """Deterministic, URL- and filesystem-safe slug for a fixture. Single source of
    truth, imported by both tools/cv_tactics.py and viz/server.py so a CV run and the
    live endpoint agree on the same key. `date` may be a date or an ISO string."""
    d = date.isoformat() if hasattr(date, "isoformat") else str(date)
    raw = f"{home}_{away}_{d}".lower()
    return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")


def _entanglement(p) -> float:
    """The bivariate-Poisson shared covariance lambda3, if that goals law is live —
    the 'entanglement' between the two scorelines. 0.0 under independent Poisson/DC."""
    return float(getattr(p.goals, "lam3", 0.0) or 0.0)


def _fingerprint(p, team: str) -> dict:
    """A compact tactical fingerprint for a side, on a 0..100 scale, derived from the
    goals model's attack/defence strengths and Elo. Not a claim about a specific XI —
    a read of the side's established profile that the lens then plays forward."""
    att = float(p.goals.attack.get(team, 0.0))      # log-scale DC attack
    dfc = float(p.goals.defence.get(team, 0.0))     # log-scale DC defence (lower = better)
    elo = float(p.elo.get(team, config.ELO_START))

    def squash(x: float) -> float:                  # logistic 0..100
        return 100.0 / (1.0 + math.exp(-x))

    threat = squash(2.2 * att)                       # attacking output
    solidity = squash(-2.2 * dfc)                    # defensive solidity (invert sign)
    # tempo: distance from a "park-the-bus" profile — high attack and a willingness to
    # trade chances reads as up-tempo / front-foot.
    tempo = squash(1.6 * att + 0.8 * dfc)
    control = max(0.0, min(100.0, (elo - 1500.0) / 8.0 + 50.0))
    return {
        "threat": round(threat, 1),
        "solidity": round(solidity, 1),
        "tempo": round(tempo, 1),
        "control": round(control, 1),
        "attack": round(att, 3),
        "defence": round(dfc, 3),
        "elo": round(elo, 1),
    }


def project(p, home: str, away: str, neutral: bool = True) -> dict:
    """Pre-match superposition packet, built from the passed-in Predictor `p`: the full
    scoreline-amplitude grid, the 1X2 outcome distribution, expected goals/shots, each
    side's tactical fingerprint and the lambda3 entanglement. Always available."""
    r = p.predict(home, away, neutral=neutral, log=False)
    grid, lh, la = p.goals.scoreline_grid(home, away, neutral=neutral)
    n = len(grid)

    # flatten to amplitude cells (skip negligible mass to keep the payload light)
    cells = []
    for i in range(n):
        for j in range(n):
            pr = grid[i][j]
            if pr >= 1e-4:
                cells.append({"h": i, "a": j, "p": round(pr, 5)})
    cells.sort(key=lambda c: c["p"], reverse=True)
    top = cells[:8]

    # marginal goal distributions (per-side goal sparkbars)
    gh = [round(sum(grid[i][j] for j in range(n)), 5) for i in range(n)]
    ga = [round(sum(grid[i][j] for i in range(n)), 5) for j in range(n)]

    # expected shots: honest scaling of xG by a typical conversion rate, so the board
    # can show "shots" without pretending to event-level precision.
    conv = 0.10
    shots_h = round(lh / conv, 1)
    shots_a = round(la / conv, 1)

    return {
        "kind": "projection",
        "home": home, "away": away, "neutral": neutral,
        "outcome": {"p_home": round(r["p_home"], 4),
                    "p_draw": round(r["p_draw"], 4),
                    "p_away": round(r["p_away"], 4)},
        "xg": {"home": round(lh, 3), "away": round(la, 3)},
        "exp_shots": {"home": shots_h, "away": shots_a},
        "top_scoreline": r["top_scoreline"],
        "grid": {"max_goals": n - 1, "cells": cells, "top": top,
                 "goals_home": gh, "goals_away": ga},
        "entanglement": round(_entanglement(p), 4),
        "goals_model": config.GOALS_MODEL,
        "fingerprint": {"home": _fingerprint(p, home),
                        "away": _fingerprint(p, away)},
        "elo": {"home": round(r["elo_home"], 1), "away": round(r["elo_away"], 1)},
    }


def _momentum(timeline: list[dict] | None, xg_home: float, xg_away: float) -> list[dict]:
    """A cumulative-threat series for the scrubber. With a real event timeline, build
    momentum from it; otherwise spread the projected xG smoothly across 90' so the
    scrubber still animates pre-match (or when the timeline is unavailable)."""
    series = []
    if timeline:
        ch = ca = 0.0
        for ev in sorted(timeline, key=lambda e: e.get("minute", 0)):
            w = float(ev.get("weight", 1.0))
            side = ev.get("side")
            if side == "home":
                ch += w
            elif side == "away":
                ca += w
            series.append({"minute": ev.get("minute", 0),
                           "home": round(ch, 3), "away": round(ca, 3),
                           "type": ev.get("type"), "side": side,
                           "label": ev.get("label")})
        return series
    steps = 18
    for k in range(steps + 1):
        f = k / steps
        series.append({"minute": int(90 * f),
                       "home": round(xg_home * f, 3),
                       "away": round(xg_away * f, 3)})
    return series


def collapse(packet: dict, real_score: tuple[int, int] | None = None,
             timeline: list[dict] | None = None) -> dict:
    """Overlay an observed match onto the pre-match superposition: mark the actual
    scoreline cell, record how (im)probable it was, and attach a momentum series. When
    `timeline` is empty (the common case on the free SportsDB key) the momentum falls
    back to the projected-xG curve and the view degrades to a score + xG overlay."""
    packet = dict(packet)
    xg = packet.get("xg", {"home": 0.0, "away": 0.0})
    packet["momentum"] = _momentum(timeline, xg.get("home", 0.0), xg.get("away", 0.0))

    if real_score is not None:
        hs, as_ = real_score
        cell_p = None
        for c in packet.get("grid", {}).get("cells", []):
            if c["h"] == hs and c["a"] == as_:
                cell_p = c["p"]
                break
        outcome = ("home" if hs > as_ else "away" if as_ > hs else "draw")
        po = packet["outcome"][f"p_{outcome}"]
        packet["kind"] = "collapse"
        packet["actual"] = {
            "home_score": hs, "away_score": as_, "outcome": outcome,
            "score_prob": cell_p,                      # P the model gave this exact score
            "outcome_prob": po,                        # P the model gave this result
            "surprise": round(-math.log2(max(po, 1e-9)), 2),   # bits of surprise
        }
    return packet


if __name__ == "__main__":   # quick smoke
    from models.predict import Predictor
    p = Predictor()
    pkt = project(p, "Brazil", "Morocco", neutral=True)
    print("projection:", pkt["outcome"], "lambda3=", pkt["entanglement"],
          "top=", pkt["top_scoreline"])
    pkt = collapse(pkt, real_score=(2, 1))
    print("collapse:", pkt["actual"])
