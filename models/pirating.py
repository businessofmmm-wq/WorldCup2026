"""
Pi-ratings (Constantinou & Fenton, 2013) — a second team-strength signal.

Unlike Elo (win/draw/loss + a goal-difference K), pi-ratings learn from the
*margin* of every result, keep SEPARATE home and away ratings per team, and
weight recent matches via the learning rate. They beat Elo and were profitable
vs bookmaker odds over five EPL seasons. Here they give an independent 1X2 the
ensemble blends for a resolution (sharpness) gain — validated leakage-free to
improve held-out RPS/Brier/LogLoss/ECE on the 2022+ window.

Pure Python, no numpy. Hyperparameters fall back to defaults but are read from
config when present (PI_LAMBDA, PI_GAMMA, PI_DRAW_WIDTH, PI_SCALE). Mapping
constants b=10, c=3 are the paper's defaults. Ratings persist to
data/pi_params.json (written by `run.py train`, read by the predictor) so the
49k-match replay runs once at train time, not on every prediction.
"""
from __future__ import annotations
import json
import math
import os

try:
    import config
except Exception:  # pragma: no cover - allows standalone import/testing
    config = None

_B = 10.0
_C = 3.0
_DEF = {"PI_LAMBDA": 0.06, "PI_GAMMA": 0.5, "PI_DRAW_WIDTH": 0.80, "PI_SCALE": 1.10}


def _cfg(name: str) -> float:
    return float(getattr(config, name, _DEF[name])) if config else _DEF[name]


def _params_path() -> str:
    base = getattr(config, "DATA_DIR", None) if config else None
    return os.path.join(base or "data", "pi_params.json")


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


def save(pr: "PiRatings", path: str | None = None) -> str:
    path = path or _params_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(pr.r, fh)
    return path


def compute_and_save(verbose: bool = False) -> "PiRatings":
    pr = compute(verbose=verbose)
    p = save(pr)
    if verbose:
        print(f"  persisted pi-ratings -> {os.path.basename(p)}")
    return pr


def load_cached(path: str | None = None) -> "PiRatings | None":
    """Load persisted pi-ratings (data/pi_params.json). None if absent."""
    path = path or _params_path()
    try:
        with open(path, encoding="utf-8") as fh:
            r = json.load(fh)
    except (FileNotFoundError, ValueError):
        return None
    pr = PiRatings()
    pr.r = {t: [float(v[0]), float(v[1])] for t, v in r.items()}
    return pr


def load() -> "PiRatings":
    """Cached ratings if available, else recompute from history."""
    return load_cached() or compute(verbose=False)
