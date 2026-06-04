"""
Dixon-Coles style goals model (pure Python, no numpy/scipy).

Goals are modelled as Poisson with team attack/defence strengths and a global
home-advantage term:

    lambda_home = exp(mu + gamma + attack[home] - defence[away])
    lambda_away = exp(mu        + attack[away] - defence[home])

Parameters are fit by maximum likelihood via gradient ascent, with an
exponential time-decay weight so recent form dominates (Dixon & Coles, 1997).
Identifiability is fixed by re-centring attack and defence to mean zero.

At prediction time we build the full scoreline probability grid and apply the
Dixon-Coles low-score correction (tau) so 0-0/1-0/0-1/1-1 are calibrated.
"""
from __future__ import annotations
import math
import os
import json
import datetime as dt

import config
from db import connect

_PARAMS_FILE = os.path.join(config.DATA_DIR, "dc_params.json")


def _poisson_pmf(k: int, lam: float) -> float:
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * lam ** k / math.factorial(k)


def _tau(x: int, y: int, lh: float, la: float, rho: float) -> float:
    """Dixon-Coles low-score dependency correction."""
    if x == 0 and y == 0:
        return 1.0 - lh * la * rho
    if x == 0 and y == 1:
        return 1.0 + lh * rho
    if x == 1 and y == 0:
        return 1.0 + la * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


class GoalsModel:
    """Holds fitted parameters and produces scoreline grids for fixtures."""

    def __init__(self, attack, defence, mu, gamma):
        self.attack = attack      # {team: float}
        self.defence = defence    # {team: float}
        self.mu = mu              # baseline log goal rate
        self.gamma = gamma        # home advantage (log scale)

    # -- expected goals ---------------------------------------------------- #
    def expected_goals(self, home: str, away: str, neutral: bool = True):
        a_h = self.attack.get(home, 0.0)
        d_h = self.defence.get(home, 0.0)
        a_a = self.attack.get(away, 0.0)
        d_a = self.defence.get(away, 0.0)
        g = 0.0 if neutral else self.gamma
        lam_h = math.exp(self.mu + g + a_h - d_a)
        lam_a = math.exp(self.mu + a_a - d_h)
        return lam_h, lam_a

    # -- scoreline grid + 1X2 --------------------------------------------- #
    def scoreline_grid(self, home: str, away: str, neutral: bool = True,
                       max_goals: int | None = None):
        max_goals = max_goals or config.DC_MAX_GOALS
        lam_h, lam_a = self.expected_goals(home, away, neutral)
        ph = [_poisson_pmf(i, lam_h) for i in range(max_goals + 1)]
        pa = [_poisson_pmf(j, lam_a) for j in range(max_goals + 1)]
        grid = [[0.0] * (max_goals + 1) for _ in range(max_goals + 1)]
        total = 0.0
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p = ph[i] * pa[j] * _tau(i, j, lam_h, lam_a, config.DC_RHO)
                p = max(p, 0.0)
                grid[i][j] = p
                total += p
        if total > 0:  # renormalise (tau slightly perturbs the mass)
            for i in range(max_goals + 1):
                for j in range(max_goals + 1):
                    grid[i][j] /= total
        return grid, lam_h, lam_a

    def predict(self, home: str, away: str, neutral: bool = True) -> dict:
        grid, lam_h, lam_a = self.scoreline_grid(home, away, neutral)
        n = len(grid)
        p_home = p_draw = p_away = 0.0
        best_p, best_score = -1.0, (0, 0)
        for i in range(n):
            for j in range(n):
                p = grid[i][j]
                if i > j:
                    p_home += p
                elif i == j:
                    p_draw += p
                else:
                    p_away += p
                if p > best_p:
                    best_p, best_score = p, (i, j)
        return {
            "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
            "exp_home_goals": lam_h, "exp_away_goals": lam_a,
            "top_scoreline": f"{best_score[0]}-{best_score[1]}",
            "top_scoreline_p": best_p,
        }


# ------------------------------------------------------------------------- #
# Fitting
# ------------------------------------------------------------------------- #
def _load_matches():
    cutoff = dt.date.today() - dt.timedelta(days=365 * config.DC_RECENT_YEARS)
    with connect() as conn:
        return conn.execute(
            """
            SELECT match_date, home_team, away_team, home_score, away_score, neutral
            FROM matches
            WHERE status='finished' AND home_score IS NOT NULL
                  AND away_score IS NOT NULL AND match_date >= %s
            ORDER BY match_date
            """,
            (cutoff,),
        ).fetchall()


def fit(persist: bool = True, verbose: bool = True) -> GoalsModel:
    rows = _load_matches()
    if not rows:
        raise RuntimeError("No matches to fit on — run ingestion first.")

    today = dt.date.today()
    half_life = config.DC_HALF_LIFE_DAYS
    teams = set()
    data = []  # (home, away, hs, as, neutral, weight)
    for d, home, away, hs, as_, neutral in rows:
        age_days = (today - d).days
        w = 0.5 ** (age_days / half_life)  # exponential time decay
        data.append((home, away, hs, as_, neutral, w))
        teams.add(home)
        teams.add(away)

    attack = {t: 0.0 for t in teams}
    defence = {t: 0.0 for t in teams}
    total_goals = sum(r[2] + r[3] for r in data)
    n_sides = 2 * len(data)
    mu = math.log(max(total_goals / n_sides, 0.1))
    gamma = 0.25  # sensible starting home advantage

    # Per-parameter observation weight so each team's step is the AVERAGE
    # residual (not the raw sum) — converges fast regardless of how many
    # matches a team has. Use decayed weights as the effective sample size.
    w_team = {t: 0.0 for t in teams}
    w_nonneutral = 0.0
    for home, away, hs, as_, neutral, w in data:
        w_team[home] += w
        w_team[away] += w
        if not neutral:
            w_nonneutral += w
    w_total = sum(w_team.values())

    lr = config.DC_LR
    for it in range(config.DC_ITERS):
        g_att = {t: 0.0 for t in teams}
        g_def = {t: 0.0 for t in teams}
        g_mu = 0.0
        g_gamma = 0.0
        for home, away, hs, as_, neutral, w in data:
            ha = 0.0 if neutral else gamma
            lam_h = math.exp(mu + ha + attack[home] - defence[away])
            lam_a = math.exp(mu + attack[away] - defence[home])
            r_h = w * (hs - lam_h)   # gradient of Poisson ll wrt log-rate
            r_a = w * (as_ - lam_a)
            g_att[home] += r_h
            g_def[away] -= r_h
            g_att[away] += r_a
            g_def[home] -= r_a
            g_mu += r_h + r_a
            if not neutral:
                g_gamma += r_h
        # gradient ascent step, normalised per-parameter by its sample weight
        reg = config.DC_REG
        for t in teams:
            wt = w_team[t] or 1.0
            attack[t] += lr * (g_att[t] / wt - reg * attack[t])
            defence[t] += lr * (g_def[t] / wt - reg * defence[t])
        mu += lr * g_mu / w_total
        if w_nonneutral:
            gamma += lr * g_gamma / w_nonneutral
        gamma = max(0.0, min(gamma, 1.0))
        # re-centre for identifiability
        ma = sum(attack.values()) / len(teams)
        md = sum(defence.values()) / len(teams)
        for t in teams:
            attack[t] -= ma
            defence[t] -= md

    if verbose:
        print(f"  Dixon-Coles fit: {len(data):,} matches, {len(teams)} teams, "
              f"mu={mu:.3f}, home_adv={gamma:.3f}")

    model = GoalsModel(attack, defence, mu, gamma)
    if persist:
        _persist(model, data, verbose)
    return model


def _persist(model: GoalsModel, data, verbose):
    counts: dict[str, int] = {}
    last: dict[str, dt.date] = {}
    for home, away, *_ in data:
        counts[home] = counts.get(home, 0) + 1
        counts[away] = counts.get(away, 0) + 1
    with connect() as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO team_ratings (team, attack, defence, updated_at)
            VALUES (%s,%s,%s, now())
            ON CONFLICT (team) DO UPDATE
              SET attack = EXCLUDED.attack,
                  defence = EXCLUDED.defence,
                  updated_at = now()
            """,
            [(t, model.attack[t], model.defence[t]) for t in model.attack],
        )
    with open(_PARAMS_FILE, "w", encoding="utf-8") as fh:
        json.dump({"mu": model.mu, "gamma": model.gamma}, fh)
    if verbose:
        print(f"  persisted attack/defence for {len(model.attack)} teams")


def load() -> GoalsModel:
    """Rebuild a GoalsModel from persisted ratings (skips refitting)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT team, attack, defence FROM team_ratings WHERE attack IS NOT NULL"
        ).fetchall()
    attack = {t: a for t, a, d in rows}
    defence = {t: d for t, a, d in rows}
    mu, gamma = 0.2, 0.25
    try:
        with open(_PARAMS_FILE, encoding="utf-8") as fh:
            saved = json.load(fh)
            mu, gamma = saved["mu"], saved["gamma"]
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return GoalsModel(attack, defence, mu=mu, gamma=gamma)


if __name__ == "__main__":
    m = fit()
    # sanity check a marquee fixture
    for h, a in [("Brazil", "Argentina"), ("France", "England"), ("Spain", "Germany")]:
        p = m.predict(h, a, neutral=True)
        print(f"  {h} vs {a}: H {p['p_home']:.0%} / D {p['p_draw']:.0%} / A {p['p_away']:.0%}"
              f"  xG {p['exp_home_goals']:.2f}-{p['exp_away_goals']:.2f}  most likely {p['top_scoreline']}")
