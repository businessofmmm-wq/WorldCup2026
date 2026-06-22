"""
Post-hoc probability recalibration for the 1X2 ensemble. Pure Python — no numpy.

Composable recalibrators, each fit on a held-out stream of (probs, outcome) pairs
and applied at predict time. Every one is a NO-OP at its identity parameter, so it
is safe to ship disabled and switch on only after `run.py backtest` confirms a
held-out gain (the engine's standing rule: keep a change only if RPS improves).

  - Vector (per-class) temperature   -> sharpens/softens each outcome class
                                         independently. Targets calibration error
                                         (ECE) and log-loss.        [Phase 1]
  - Shrinkage to the base-rate prior -> blends each forecast toward the marginal
                                         1X2 frequencies, trading a little
                                         resolution for reliability. Targets the
                                         Brier score (and RPS).      [Phase 2]
  - Blend weights (Elo/DC/pi)        -> optimal convex mix of the component 1X2s.
                                         Targets log-loss / RPS.     [Phase 4]

Fitters are dependency-free coordinate/grid searches over a held-out score,
mirroring the existing tune/calibrate philosophy. Outcome encoding matches
models.metrics: 0 = home, 1 = draw, 2 = away.
"""
from __future__ import annotations

from models import metrics

_EPS = 1e-12
Triple = tuple


def _mean_loss(rows, transform, loss) -> float:
    n = 0
    tot = 0.0
    for p, o in rows:
        tot += loss(transform(p), o)
        n += 1
    return tot / n if n else float("inf")


# --------------------------------------------------------------------------- #
# Phase 1 — vector (per-class) temperature scaling
# --------------------------------------------------------------------------- #
# A single scalar temperature can only sharpen/soften all three classes by the
# same exponent. Football 1X2 is asymmetric — draw probabilities are the hardest
# to calibrate — so a per-class temperature (T_home, T_draw, T_away) gives the
# recalibration two extra degrees of freedom, which is what reduces calibration
# error beyond a single global T. Identity is (1, 1, 1): probabilities unchanged.

def apply_vector_temperature(p: Triple, temps: Triple) -> Triple:
    """Raise each class probability to 1/T_i and renormalise to sum 1."""
    th, td, ta = temps
    qh = max(p[0], _EPS) ** (1.0 / th)
    qd = max(p[1], _EPS) ** (1.0 / td)
    qa = max(p[2], _EPS) ** (1.0 / ta)
    s = qh + qd + qa
    return (qh / s, qd / s, qa / s)


def fit_vector_temperature(rows, loss=metrics.log_loss, grid=None,
                           rounds: int = 4) -> Triple:
    """Coordinate-descent fit of (T_home, T_draw, T_away) on held-out `rows`,
    minimising mean `loss` (default log-loss, a strictly proper score). Returns
    the identity (1, 1, 1) when that is already optimal, so it is always safe to
    apply. `rows` is an iterable of ((p_home, p_draw, p_away), outcome)."""
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


# --------------------------------------------------------------------------- #
# Phase 2 — shrinkage toward the base-rate prior
# --------------------------------------------------------------------------- #
# An over-confident forecaster pushes mass toward 0/1 and is punished hard by the
# Brier score on the matches it gets wrong. Blending each forecast a little way
# back toward the marginal 1X2 frequencies reduces that variance:
#   p' = (1 - lam) * p + lam * prior.
# lam = 0 is the identity; lam in (0, 1) is a bias/variance trade that lowers
# Brier when the model is even mildly over-confident.

def base_rate(rows) -> Triple:
    """Empirical (home, draw, away) outcome frequencies over `rows`."""
    n = 0
    c = [0, 0, 0]
    for _p, o in rows:
        c[o] += 1
        n += 1
    if n == 0:
        return (1 / 3, 1 / 3, 1 / 3)
    return (c[0] / n, c[1] / n, c[2] / n)


def apply_shrinkage(p: Triple, lam: float, prior: Triple) -> Triple:
    """Blend a forecast toward `prior` by fraction `lam`; renormalise defensively."""
    q = [(1.0 - lam) * p[i] + lam * prior[i] for i in range(3)]
    s = sum(q) or 1.0
    return (q[0] / s, q[1] / s, q[2] / s)


def fit_shrinkage(rows, prior: Triple | None = None, loss=metrics.brier,
                  grid=None) -> float:
    """Grid-fit the shrinkage fraction lam in [0, ~0.5] minimising mean `loss`
    (default Brier). Returns 0.0 when no shrinkage helps, so it is always safe to
    apply. Pair the returned lam with `prior` (defaults to base_rate(rows))."""
    rows = list(rows)
    if not rows:
        return 0.0
    if prior is None:
        prior = base_rate(rows)
    grid = grid or [i / 100.0 for i in range(0, 51, 2)]   # 0.00 .. 0.50 step 0.02
    best_lam, best_l = 0.0, float("inf")
    for lam in grid:
        l = _mean_loss(rows, lambda p, _l=lam: apply_shrinkage(p, _l, prior), loss)
        if l < best_l - 1e-12:
            best_l, best_lam = l, lam
    return best_lam
