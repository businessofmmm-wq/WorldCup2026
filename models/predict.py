"""
Ensemble match predictor.

Combines two independent views of a fixture:
  1. Elo  -> a 1X2 probability via win-expectancy + a closeness-based draw model.
  2. Dixon-Coles -> a 1X2 probability + scoreline grid from the goals model.

The two 1X2 vectors are blended with configurable weights. Expected goals and
the most-likely scoreline come from the Dixon-Coles side (Elo has no goals
notion). Every prediction can be logged to the `predictions` table.
"""
from __future__ import annotations
import json

import config
from db import connect
from models import elo as elo_mod
from models import poisson as poisson_mod
from models import bivpoisson as bivpois_mod
from models import draw_model


def load_goals_model():
    """Load the goals model selected by config.GOALS_MODEL (bivariate Poisson,
    diagonal-inflated Poisson, or Dixon-Coles). All expose the same GoalsModel
    interface, so the rest of the engine is oblivious to which joint scoreline
    law is in play."""
    if config.GOALS_MODEL == "bivpois":
        return bivpois_mod.load()
    if config.GOALS_MODEL == "bivpois_diag":
        return bivpois_mod.load_diagonal()
    return poisson_mod.load()

# Empirical maximum draw probability for an evenly matched international.
_DRAW_MAX = config.ELO_DRAW_MAX
# Ordered-logit draw model params (b, k1, k2), if it has been fit; else None ->
# fall back to the linear closeness model below.
_DRAW = draw_model.load()


def elo_1x2(elo: dict, home: str, away: str, neutral: bool = True) -> dict:
    ra = elo.get(home, config.ELO_START)
    rb = elo.get(away, config.ELO_START)
    ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
    if _DRAW is not None:   # empirical ordered-logit mapping (preferred)
        ph, pd, pa = draw_model.probs((ra + ha) - rb, *_DRAW)
        return {"p_home": ph, "p_draw": pd, "p_away": pa}
    e = elo_mod.expected_score(ra + ha, rb)   # home win expectancy (draw=½)
    # draw probability shrinks linearly as the mismatch grows
    p_draw = max(0.0, config.ELO_DRAW_MAX * (1.0 - 2.0 * abs(e - 0.5)))
    p_home = max(0.0, e - 0.5 * p_draw)
    p_away = max(0.0, (1.0 - e) - 0.5 * p_draw)
    s = p_home + p_draw + p_away
    return {"p_home": p_home / s, "p_draw": p_draw / s, "p_away": p_away / s}


class Predictor:
    def __init__(self, elo: dict | None = None, goals: poisson_mod.GoalsModel | None = None):
        self.elo = elo if elo is not None else _load_elo()
        # Tournament-form overlay: nudge effective Elo by current-WC performance vs
        # expectation (recency-weighted, bounded). config.FORM_WEIGHT = 0 disables.
        if getattr(config, "FORM_WEIGHT", 0) > 0:
            try:
                from models import form as _form
                self.elo = _form.effective_elo(self.elo)
            except Exception:
                pass
        self.goals = goals if goals is not None else load_goals_model()
        # Squad-value prior: nudge effective Elo by club-derived talent (centred
        # log market value). Off when weight=0 or no values ingested. Leakage-free
        # basis: see config.ENSEMBLE_VALUE_WEIGHT.
        if getattr(config, "ENSEMBLE_VALUE_WEIGHT", 0.0) > 0:
            try:
                import math as _math
                from sources import squadvalue as _sv
                _vals = _sv.load()
                if _vals:
                    _logs = {t: _math.log10(v) for t, v in _vals.items() if v > 0}
                    _mean = sum(_logs.values()) / len(_logs)
                    _g = config.ENSEMBLE_VALUE_WEIGHT
                    for _t, _lv in _logs.items():
                        self.elo[_t] = self.elo.get(_t, config.ELO_START) + _g * (_lv - _mean)
            except Exception:
                pass
        # Pi-ratings signal, loaded once from cache (data/pi_params.json) when
        # the ensemble weight is on. Off (None) keeps the live path Elo+DC only.
        self.pi = None
        if getattr(config, "ENSEMBLE_PI_WEIGHT", 0.0) > 0:
            try:
                from models import pirating
                self.pi = pirating.load_cached()
            except Exception:
                self.pi = None

    def predict(self, home: str, away: str, neutral: bool = True,
                log: bool = False, match_date=None) -> dict:
        e = elo_1x2(self.elo, home, away, neutral)
        gm = self.goals.predict(home, away, neutral)   # bivariate-Poisson or DC

        we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
        wsum = we + wd
        p_home = (we * e["p_home"] + wd * gm["p_home"]) / wsum
        p_draw = (we * e["p_draw"] + wd * gm["p_draw"]) / wsum
        p_away = (we * e["p_away"] + wd * gm["p_away"]) / wsum
        # Pi-ratings blend (resolution gain), pre-temper so calibration sees it.
        _wp = getattr(config, "ENSEMBLE_PI_WEIGHT", 0.0)
        if _wp and self.pi is not None:
            from models import pirating
            _pi = pirating.predict_1x2(self.pi, home, away, neutral)
            p_home = (1.0 - _wp) * p_home + _wp * _pi["p_home"]
            p_draw = (1.0 - _wp) * p_draw + _wp * _pi["p_draw"]
            p_away = (1.0 - _wp) * p_away + _wp * _pi["p_away"]
            _n = p_home + p_draw + p_away
            p_home, p_draw, p_away = p_home / _n, p_draw / _n, p_away / _n
        p_home, p_draw, p_away = _temper(p_home, p_draw, p_away)
        # Optional shrinkage toward the base-rate prior (Brier/RPS). Off by default.
        _lam = getattr(config, "ENSEMBLE_SHRINKAGE", 0.0)
        _prior = getattr(config, "ENSEMBLE_PRIOR", None)
        if _lam and _prior:
            from models import calibrate
            p_home, p_draw, p_away = calibrate.apply_shrinkage(
                (p_home, p_draw, p_away), _lam, _prior)

        result = {
            "home": home, "away": away, "neutral": neutral,
            "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
            "exp_home_goals": gm["exp_home_goals"],
            "exp_away_goals": gm["exp_away_goals"],
            "top_scoreline": gm["top_scoreline"],
            "elo_home": self.elo.get(home, config.ELO_START),
            "elo_away": self.elo.get(away, config.ELO_START),
            "components": {"elo": e, "goals": gm, "goals_model": config.GOALS_MODEL},
        }
        if log:
            self._log(result, match_date)
        return result

    def _log(self, r: dict, match_date):
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO predictions
                    (match_date, home_team, away_team, neutral, p_home, p_draw,
                     p_away, exp_home_goals, exp_away_goals, top_scoreline, model, detail)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'ensemble',%s)
                """,
                (match_date, r["home"], r["away"], r["neutral"], r["p_home"],
                 r["p_draw"], r["p_away"], r["exp_home_goals"], r["exp_away_goals"],
                 r["top_scoreline"], json.dumps(r["components"])),
            )


def _temper(p_home: float, p_draw: float, p_away: float) -> tuple[float, float, float]:
    """Apply the calibration temperature and renormalise to a probability triple.

    If config.ENSEMBLE_TEMPERATURE_VEC is set (a [T_home, T_draw, T_away] list), a
    per-class temperature is applied instead of the scalar — better ECE on the
    asymmetric draw class. Falls back to the scalar temperature otherwise."""
    vec = getattr(config, "ENSEMBLE_TEMPERATURE_VEC", None)
    if vec:
        from models import calibrate
        return calibrate.apply_vector_temperature((p_home, p_draw, p_away), vec)
    t = config.ENSEMBLE_TEMPERATURE
    if t == 1.0:
        s = p_home + p_draw + p_away
        return p_home / s, p_draw / s, p_away / s
    inv = 1.0 / t
    qh, qd, qa = (max(p_home, 1e-9) ** inv, max(p_draw, 1e-9) ** inv,
                  max(p_away, 1e-9) ** inv)
    s = qh + qd + qa
    return qh / s, qd / s, qa / s


def _load_elo() -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT team, elo FROM team_ratings WHERE elo IS NOT NULL"
        ).fetchall()
    return {t: e for t, e in rows}


def fmt(r: dict) -> str:
    tag = "(N)" if r["neutral"] else "(H)"
    return (f"{r['home']} {tag} vs {r['away']}\n"
            f"  Win {r['p_home']:.1%} | Draw {r['p_draw']:.1%} | Win {r['p_away']:.1%}\n"
            f"  xG {r['exp_home_goals']:.2f}–{r['exp_away_goals']:.2f}  "
            f"| most likely {r['top_scoreline']}  "
            f"| Elo {r['elo_home']:.0f} vs {r['elo_away']:.0f}")


if __name__ == "__main__":
    p = Predictor()
    for h, a in [("Brazil", "Argentina"), ("France", "England"),
                 ("Spain", "Germany"), ("United States", "Mexico")]:
        print(fmt(p.predict(h, a, neutral=True)), "\n")
