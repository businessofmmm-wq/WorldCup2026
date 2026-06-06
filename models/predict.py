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
from models import draw_model

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
        self.goals = goals if goals is not None else poisson_mod.load()

    def predict(self, home: str, away: str, neutral: bool = True,
                log: bool = False, match_date=None) -> dict:
        e = elo_1x2(self.elo, home, away, neutral)
        dc = self.goals.predict(home, away, neutral)

        we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
        wsum = we + wd
        p_home = (we * e["p_home"] + wd * dc["p_home"]) / wsum
        p_draw = (we * e["p_draw"] + wd * dc["p_draw"]) / wsum
        p_away = (we * e["p_away"] + wd * dc["p_away"]) / wsum
        p_home, p_draw, p_away = _temper(p_home, p_draw, p_away)

        result = {
            "home": home, "away": away, "neutral": neutral,
            "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
            "exp_home_goals": dc["exp_home_goals"],
            "exp_away_goals": dc["exp_away_goals"],
            "top_scoreline": dc["top_scoreline"],
            "elo_home": self.elo.get(home, config.ELO_START),
            "elo_away": self.elo.get(away, config.ELO_START),
            "components": {"elo": e, "dixon_coles": dc},
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
    """Apply the calibration temperature and renormalise to a probability triple."""
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
