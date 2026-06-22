"""
Pi-ratings (Constantinou & Fenton, 2013) — a second team-strength signal.

Unlike Elo (win/draw/loss + a goal-difference K), pi-ratings learn from the
*margin* of every result, keep SEPARATE home and away ratings per team, and
weight recent matches via the learning rate. They beat Elo and were profitable
vs bookmaker odds over five EPL seasons. Here they give an independent 1X2 the
ensemble can blend for a resolution (sharpness) gain aimed at RPS.

Pure Python, no numpy. Self-contained: hyperparameters fall back to sensible
defaults but can be overridden on config (PI_LAMBDA, PI_GAMMA, PI_DRAW_WIDTH,
PI_SCALE) once tuned. Mapping constants b=10, c=3 are the paper's defaults.
"""
from __future__ import annotations
import math

try:
    import config
except Exception:  # pragma: no cover - allows standalone import/testing
    config = None

_B = 10.0
_C = 3.0
_DEF = {"PI_LAMBDA": 0.06, "PI_GAMMA": 0.5, "PI_DRAW_WIDTH": 0.80, "PI_SCALE": 1.10}


def _cfg(name: str) -> float:
    return float(getattr(config, name, _DEF[name])) if config else _DEF[name]


def psi(r: float) -> float:
    """Rating -> expected goal advantage (signed): sign(r)*(b^(|r|/c) - 1)."""
    return math.copysign(_B ** (abs(r) / _C) - 1.0, r)


def _psi_inv_mag(goal_err: float) -> float:
    """Goal-scale error -> rating-scale magnitude: c*log_b(1+|err|)."""
    return _C * math.log(1.0 + abs(goal_err), _B)


class PiRatings:
    """Holds [home_rating, away_rating] per team; updates match by match."""

    def __init__(self, lam: float | None = None, gamma: float | None = None):
        self.lam = _cfg("PI_LAMBDA") if lam is None else lam
        self.gamma = _cfg("PI_GAMMA") if gamma is None else gamma
        self.r: dict[str, list] = {}

    def _get(self, team: str) -> list:
        return self.r.setdefault(team, [0.0, 0.0])

    def expected_gd(self, home: str, away: str, neutral: bool = False) -> float:
        rh, ra = self._get(home), self._get(away)
        if neutral:
            return psi((rh[0] + rh[1]) / 2.0) - psi((ra[0] + ra[1]) / 2.0)
        return psi(rh[0]) - psi(ra[1])

    def update(self, home: str, away: str, home_goals: int, away_goals: int,
               neutral: bool = False) -> None:
        rh, ra = self._get(home), self._get(away)
        err = (home_goals - away_goals) - self.expected_gd(home, away, neutral)
        d = math.copysign(self.lam * _psi_inv_mag(err), err)
        rh[0] += d
        rh[1] += self.gamma * d
        ra[1] -= d
        ra[0] -= self.gamma * d

    def rating(self, team: str) -> list:
        return self._get(team)


def gd_to_1x2(gd: float, draw_width: float | None = None,
              scale: float | None = None) -> dict:
    """Map an expected goal difference to a 1X2 via a logistic ordered model."""
    dw = _cfg("PI_DRAW_WIDTH") if draw_width is None else draw_width
    sc = _cfg("PI_SCALE") if scale is None else scale
    f = lambda x: 1.0 / (1.0 + math.exp(-x / sc))
    p_home, p_away = f(gd - dw), f(-gd - dw)
    p_draw = max(0.0, 1.0 - p_home - p_away)
    s = p_home + p_draw + p_away
    return {"p_home": p_home / s, "p_draw": p_draw / s, "p_away": p_away / s}


def predict_1x2(ratings: "PiRatings", home: str, away: str,
                neutral: bool = True) -> dict:
    return gd_to_1x2(ratings.expected_gd(home, away, neutral))


def compute(verbose: bool = False) -> "PiRatings":
    """Replay finished matches (chronological) into pi-ratings. Mirrors elo.compute."""
    from db import connect
    pr = PiRatings()
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT home_team, away_team, home_score, away_score, neutral
            FROM matches
            WHERE status='finished' AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
            ORDER BY match_date, id
            """
        ).fetchall()
    for home, away, hs, as_, neutral in rows:
        pr.update(home, away, hs, as_, neutral=bool(neutral))
    if verbose:
        print(f"  pi-ratings over {len(rows):,} matches, {len(pr.r)} teams")
    return pr


def load() -> "PiRatings":
    return compute(verbose=False)
