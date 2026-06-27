"""
Empirical Elo -> 1X2 mapping via an ordered-logistic model.

The hand-built draw model in `predict.elo_1x2` shrinks draw mass linearly with
the rating mismatch — serviceable, but arbitrary. This fits the real thing: an
ordered logit over the three ordered outcomes away < draw < home, driven by the
pre-match Elo gap `d = (rating_home + home_adv) - rating_away`.

    z  = b * (d / 400)                      (Elo gap in logistic units, scaled)
    F1 = sigmoid(k1 - z),  F2 = sigmoid(k2 - z)      with k1 < k2
    P(away) = F1     P(draw) = F2 - F1     P(home) = 1 - F2

Three parameters (b, k1, k2) fit by maximum likelihood (gradient ascent) on every
historical match's pre-match Elo gap and realised result. The thresholds set how
wide the "draw band" is; b sets how fast it tilts to a favourite — both learned
from data rather than assumed. Params persist to data/draw_params.json.
"""
from __future__ import annotations
import math
import os
import json

import config
from db import connect
from models.elo import _k_for, _gd_multiplier

_PARAMS_FILE = os.path.join(config.DATA_DIR, "draw_params.json")
# Outcome order for the latent: away(0) < draw(1) < home(2).


def _sigmoid(u: float) -> float:
    if u >= 0:
        z = math.exp(-u)
        return 1.0 / (1.0 + z)
    z = math.exp(u)
    return z / (1.0 + z)


def probs(d: float, b: float, k1: float, k2: float) -> tuple[float, float, float]:
    """(P_home, P_draw, P_away) from the Elo gap d and ordered-logit params."""
    z = b * (d / 400.0)
    f1 = _sigmoid(k1 - z)
    f2 = _sigmoid(k2 - z)
    p_away = f1
    p_draw = max(f2 - f1, 1e-9)
    p_home = 1.0 - f2
    s = p_home + p_draw + p_away
    return (p_home / s, p_draw / s, p_away / s)


def collect_samples(upto=None) -> list[tuple]:
    """Replay Elo over history; return (date, d, outcome) per match.

    `d` is the pre-match Elo gap including home advantage; outcome uses the
    metrics encoding (0 home, 1 draw, 2 away). If `upto` is given, only matches
    strictly before it are returned (the ratings still replay over everything up
    to each match, so each `d` is leakage-free).
    """
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
    out = []
    for d_, home, away, hs, as_, tourn, neutral in rows:
        ra = elo.get(home, config.ELO_START)
        rb = elo.get(away, config.ELO_START)
        ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
        gap = (ra + ha) - rb
        outcome = 0 if hs > as_ else (1 if hs == as_ else 2)
        if upto is None or d_ < upto:
            out.append((d_, gap, outcome))
        # Elo update (mirrors elo.compute so the gaps match the live ratings)
        exp_home = 1.0 / (1.0 + 10 ** ((rb - ra - ha) / 400.0))
        sh = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
        mult = _gd_multiplier(hs - as_) if config.ELO_USE_GD else 1.0
        k = _k_for(tourn) * config.ELO_K_SCALE * mult
        delta = k * (sh - exp_home)
        elo[home] = ra + delta
        elo[away] = rb - delta
    return out


def fit(samples=None, iters: int = 800, lr: float = 0.5,
        persist: bool = True, verbose: bool = True) -> tuple[float, float, float]:
    """MLE-fit (b, k1, k2) on (·, d, outcome) samples by gradient ascent."""
    if samples is None:
        samples = collect_samples()
    data = [(gap, o) for _, gap, o in samples]
    n = len(data)
    b, k1, k2 = 1.2, -0.45, 0.45  # sensible start: symmetric draw band
    for _ in range(iters):
        gb = gk1 = gk2 = 0.0
        for gap, o in data:
            z = b * (gap / 400.0)
            f1 = _sigmoid(k1 - z)
            f2 = _sigmoid(k2 - z)
            d1 = f1 * (1.0 - f1)   # dF1/d(k1-z)
            d2 = f2 * (1.0 - f2)
            x = gap / 400.0
            if o == 0:             # home: LL = log(1 - F2)
                p = max(1.0 - f2, 1e-12)
                dF2 = -1.0 / p
                gk2 += dF2 * d2
                gb += dF2 * (-d2 * x)
            elif o == 1:           # draw: LL = log(F2 - F1)
                p = max(f2 - f1, 1e-12)
                dF2 = 1.0 / p
                dF1 = -1.0 / p
                gk2 += dF2 * d2
                gk1 += dF1 * d1
                gb += dF2 * (-d2 * x) + dF1 * (-d1 * x)
            else:                  # away (o == 2): LL = log(F1)
                p = max(f1, 1e-12)
                dF1 = 1.0 / p
                gk1 += dF1 * d1
                gb += dF1 * (-d1 * x)
        b += lr * gb / n
        k1 += lr * gk1 / n
        k2 += lr * gk2 / n
        if k2 <= k1 + 1e-3:        # keep the band ordered
            mid = 0.5 * (k1 + k2)
            k1, k2 = mid - 0.05, mid + 0.05
        b = max(0.1, b)
    if verbose:
        print(f"  draw model fit on {n:,} matches: b={b:.3f} k1={k1:.3f} k2={k2:.3f}")
    if persist:
        with open(_PARAMS_FILE, "w", encoding="utf-8") as fh:
            json.dump({"b": b, "k1": k1, "k2": k2}, fh)
    return b, k1, k2


def load() -> tuple[float, float, float] | None:
    """Return persisted (b, k1, k2), or None if the model hasn't been fit."""
    try:
        with open(_PARAMS_FILE, encoding="utf-8") as fh:
            p = json.load(fh)
        return p["b"], p["k1"], p["k2"]
    except (FileNotFoundError, KeyError, ValueError):
        return None


if __name__ == "__main__":
    b, k1, k2 = fit()
    for d in (-400, -200, 0, 100, 300, 600):
        ph, pd, pa = probs(d, b, k1, k2)
        print(f"  gap {d:+5}:  H {ph:.0%}  D {pd:.0%}  A {pa:.0%}")
