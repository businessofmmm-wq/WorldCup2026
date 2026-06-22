"""
Post-hoc probability recalibration for the 1X2 ensemble. Pure Python — no numpy.

Composable recalibrators, each fit on a held-out stream of (probs, outcome) pairs
and applied at predict time. Every one is a NO-OP at its identity parameter, so it
is safe to ship disabled and switch on only after `run.py backtest` confirms a
held-out gain (the engine's standing rule: keep a change only if RPS improves).

  - Vector (per-class) temperature   -> sharpens/softens each outcome class
                                         independently. Targets calibration error
                                         (ECE) and log-loss.        [Phase 1]

Fitters are dependency-free coordinate/grid searches over a held-out score,
mirroring the existing `tune`/`calibrate` philosophy. Outcome encoding matches
models.metrics: 0 = home, 1 = draw, 2 = away.
"""
from __future__ import annotations

from models import metrics

_EPS = 1e-12
Triple = tuple


# --------------------------------------------------------------------------- #
# Phase 1 — vector (per-class) temperature scaling
# --------------------------------------------------------------------------- #
# A single scalar temperature can only sharpen/soften all three classes by the
# same exponent. Football 1X2 is asymmetric — draw probabilities are the hardest
# to calibrate — so a per-class temperature (T_home, T_draw, T_away) gives the
# recalibration an extra two degrees of freedom, which is exactly what reduces the
# expected calibration error beyond what one global T can reach. Identity is
# (1, 1, 1): every probability passes through unchanged.

def apply_vector_temperature(p: Triple, temps: Triple) -> Triple:
    """Raise each class probability to 1/T_i and renormalise to sum 1."""
    th, td, ta = temps
    qh = max(p[0], _EPS) ** (1.0 / th)
    qd = max(p[1], _EPS) ** (1.0 / td)
    qa = max(p[2], _EPS) ** (1.0 / ta)
    s = qh + qd + qa
    return (qh / s, qd / s, qa / s)


def _mean_loss(rows, transform, loss) -> float:
    n = 0
    tot = 0.0
    for p, o in rows:
        tot += loss(transform(p), o)
        n += 1
    return tot / n if n else float("inf")


def fit_vector_temperature(rows, loss=metrics.log_loss, grid=None,
                           rounds: int = 4) -> Triple:
    """Coordinate-descent fit of (T_home, T_draw, T_away) on held-out `rows`.

    Minimises mean `loss` (default log-loss, a strictly proper score). Returns the
    identity (1, 1, 1) when that is already optimal, so the result is always safe
    to apply. `rows` is an iterable of ((p_home, p_draw, p_away), outcome).
    """
    rows = list(rows)
    if not rows:
        return (1.0, 1.0, 1.0)
    grid = grid or [0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1, 1.2, 1.35, 1.5, 1.8]
    temps = [1.0, 1.0, 1.0]
    for _ in range(rounds):
        for i in range(3):
            best_t, best_l = temps[i], float("inf")
            for t in grid:
                cand = list(temps)
                cand[i] = t
                tup = tuple(cand)
                l = _mean_loss(rows, lambda p, _t=tup: apply_vector_temperature(p, _t), loss)
                if l < best_l - 1e-12:
                    best_l, best_t = l, t
            temps[i] = best_t
    return tuple(temps)
