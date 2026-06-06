"""
Probabilistic scoring metrics for 1X2 (home / draw / away) forecasts.

Pure Python — no numpy. Everything operates on a probability triple
`p = (p_home, p_draw, p_away)` and an integer outcome `o` in {0, 1, 2}
(0 = home win, 1 = draw, 2 = away win).

The headline metric for ordered 1X2 football forecasts is the **Ranked
Probability Score** (Epstein 1969; popularised for football by Constantinou &
Fenton, 2012). It respects the ordering home > draw > away, so predicting a draw
when the truth is an away win is penalised less than predicting a home win.
Lower is better for RPS / log-loss / Brier; higher is better for accuracy.
"""
from __future__ import annotations
import math
from collections import defaultdict

# Outcome encoding used everywhere in the backtest.
HOME, DRAW, AWAY = 0, 1, 2
_EPS = 1e-15


def outcome_index(home_score: int, away_score: int) -> int:
    """Map a final score to an outcome class (0 home, 1 draw, 2 away)."""
    if home_score > away_score:
        return HOME
    if home_score == away_score:
        return DRAW
    return AWAY


def rps(p: tuple[float, float, float], o: int) -> float:
    """Ranked Probability Score for an ordered 3-outcome forecast.

    RPS = 1/(r-1) * sum_{i=1..r-1} (CP_i - CO_i)^2, with r = 3 classes,
    CP the cumulative predicted and CO the cumulative observed (one-hot)
    distribution over the ordered classes home < draw < away.
    """
    cp1 = p[0]                 # P(home)
    cp2 = p[0] + p[1]          # P(home or draw)
    co1 = 1.0 if o == HOME else 0.0
    co2 = 1.0 if o in (HOME, DRAW) else 0.0
    return 0.5 * ((cp1 - co1) ** 2 + (cp2 - co2) ** 2)


def log_loss(p: tuple[float, float, float], o: int) -> float:
    """Negative log-likelihood of the realised outcome (a.k.a. ignorance)."""
    return -math.log(max(p[o], _EPS))


def brier(p: tuple[float, float, float], o: int) -> float:
    """Multiclass Brier score: squared error against the one-hot outcome."""
    return sum((p[i] - (1.0 if i == o else 0.0)) ** 2 for i in range(3))


def hit(p: tuple[float, float, float], o: int) -> float:
    """1 if the most-likely class is the outcome, else 0 (argmax accuracy)."""
    return 1.0 if max(range(3), key=lambda i: p[i]) == o else 0.0


def score_stream(rows: list[tuple[tuple, int]]) -> dict:
    """Aggregate metrics over an iterable of (probs, outcome) pairs.

    Returns mean RPS, log-loss, Brier, accuracy and the sample size `n`.
    """
    n = 0
    s_rps = s_ll = s_brier = s_hit = 0.0
    for p, o in rows:
        n += 1
        s_rps += rps(p, o)
        s_ll += log_loss(p, o)
        s_brier += brier(p, o)
        s_hit += hit(p, o)
    if n == 0:
        return {"n": 0, "rps": float("nan"), "log_loss": float("nan"),
                "brier": float("nan"), "acc": float("nan")}
    return {"n": n, "rps": s_rps / n, "log_loss": s_ll / n,
            "brier": s_brier / n, "acc": s_hit / n}


def calibration(rows: list[tuple[tuple, int]], cls: int = HOME,
                bins: int = 10) -> list[tuple]:
    """Reliability table for one class: (bin_lo, bin_hi, mean_pred, emp_freq, n).

    For each predicted-probability decile of class `cls`, compare the mean
    predicted probability against the empirical frequency of that outcome — a
    well-calibrated model has mean_pred ~= emp_freq in every bin.
    """
    buckets: dict[int, list] = defaultdict(lambda: [0.0, 0, 0])  # [sum_p, n_event, n]
    for p, o in rows:
        pv = p[cls]
        b = min(bins - 1, int(pv * bins))
        buckets[b][0] += pv
        buckets[b][1] += 1 if o == cls else 0
        buckets[b][2] += 1
    out = []
    for b in range(bins):
        sum_p, n_event, n = buckets[b]
        if n == 0:
            continue
        out.append((b / bins, (b + 1) / bins, sum_p / n, n_event / n, n))
    return out


def reliability_error(rows: list[tuple[tuple, int]], bins: int = 10) -> float:
    """Expected calibration error averaged over the three classes (lower=better)."""
    total = 0.0
    for cls in (HOME, DRAW, AWAY):
        table = calibration(rows, cls=cls, bins=bins)
        n_all = sum(r[4] for r in table) or 1
        ece = sum(abs(mean_pred - emp) * n for _, _, mean_pred, emp, n in table)
        total += ece / n_all
    return total / 3.0
