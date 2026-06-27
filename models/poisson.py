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

# Attack/defence are log-scale; real teams live well inside +/-2. Clamping to this
# band each iteration keeps the gradient-ascent fit from diverging on sparse
# minnows (a single in-window blowout can otherwise blow a strength up without
# bound). It never binds for genuine sides, so fitted ratings are unaffected.
_AB_CLAMP = 3.0


def _safe_exp(x: float) -> float:
    """math.exp guarded against overflow on a runaway log-rate."""
    return math.exp(x if x < 30.0 else 30.0)


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

    def __init__(self, attack, defence, mu, gamma, rho: float | None = None):
        self.attack = attack      # {team: float}
        self.defence = defence    # {team: float}
        self.mu = mu              # baseline log goal rate
        self.gamma = gamma        # home advantage (log scale)
        # low-score (tau) correlation correction; tunable per-model, defaults to config
        self.rho = config.DC_RHO if rho is None else rho

    # -- expected goals ---------------------------------------------------- #
    def expected_goals(self, home: str, away: str, neutral: bool = True):
        a_h = self.attack.get(home, 0.0)
        d_h = self.defence.get(home, 0.0)
        a_a = self.attack.get(away, 0.0)
        d_a = self.defence.get(away, 0.0)
        g = 0.0 if neutral else self.gamma
        lam_h = _safe_exp(self.mu + g + a_h - d_a)
        lam_a = _safe_exp(self.mu + a_a - d_h)
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
                p = ph[i] * pa[j] * _tau(i, j, lam_h, lam_a, self.rho)
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


def fit_params(data, as_of: dt.date, *, half_life: float | None = None,
               reg: float | None = None, iters: int | None = None,
               lr: float | None = None, rho: float | None = None,
               init: "GoalsModel | None" = None, verbose: bool = False) -> "GoalsModel":
    """Fit Dixon-Coles attack/defence by MLE on `data`, time-decayed to `as_of`.

    `data` is a list of (match_date, home, away, home_score, away_score, neutral)
    rows already filtered to the desired window. Decay weights are anchored at
    `as_of` (NOT today), which is what makes a leakage-free walk-forward possible:
    every fit only ever sees matches strictly before its as-of date. `init` warm-
    starts from a previous fit so successive refits converge in far fewer
    iterations. Does NOT touch the database — callers persist if they want to.
    """
    half_life = config.DC_HALF_LIFE_DAYS if half_life is None else half_life
    reg = config.DC_REG if reg is None else reg
    iters = config.DC_ITERS if iters is None else iters
    lr = config.DC_LR if lr is None else lr

    teams = set()
    rows = []  # (home, away, hs, as_, neutral, weight)
    for d, home, away, hs, as_, neutral in data:
        age_days = (as_of - d).days
        if age_days < 0:
            continue  # guard: never let a fit see a future match
        w = 0.5 ** (age_days / half_life)  # exponential time decay
        rows.append((home, away, hs, as_, neutral, w))
        teams.add(home)
        teams.add(away)
    if not rows:
        raise RuntimeError("fit_params: no in-window matches to fit on")

    if init is not None:  # warm start from a previous fit
        attack = {t: init.attack.get(t, 0.0) for t in teams}
        defence = {t: init.defence.get(t, 0.0) for t in teams}
        mu, gamma = init.mu, init.gamma
    else:
        attack = {t: 0.0 for t in teams}
        defence = {t: 0.0 for t in teams}
        total_goals = sum(r[2] + r[3] for r in rows)
        mu = math.log(max(total_goals / (2 * len(rows)), 0.1))
        gamma = 0.25  # sensible starting home advantage

    # Per-parameter observation weight so each team's step is the AVERAGE
    # residual (not the raw sum) — converges fast regardless of how many
    # matches a team has. Use decayed weights as the effective sample size.
    w_team = {t: 0.0 for t in teams}
    w_nonneutral = 0.0
    for home, away, hs, as_, neutral, w in rows:
        w_team[home] += w
        w_team[away] += w
        if not neutral:
            w_nonneutral += w
    w_total = sum(w_team.values())

    for it in range(iters):
        g_att = {t: 0.0 for t in teams}
        g_def = {t: 0.0 for t in teams}
        g_mu = 0.0
        g_gamma = 0.0
        for home, away, hs, as_, neutral, w in rows:
            ha = 0.0 if neutral else gamma
            lam_h = _safe_exp(mu + ha + attack[home] - defence[away])
            lam_a = _safe_exp(mu + attack[away] - defence[home])
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
        for t in teams:
            wt = w_team[t] or 1.0
            attack[t] += lr * (g_att[t] / wt - reg * attack[t])
            defence[t] += lr * (g_def[t] / wt - reg * defence[t])
        mu += lr * g_mu / w_total
        if w_nonneutral:
            gamma += lr * g_gamma / w_nonneutral
        gamma = max(0.0, min(gamma, 1.0))
        # re-centre for identifiability, then clamp to keep sparse-team fits stable
        ma = sum(attack.values()) / len(teams)
        md = sum(defence.values()) / len(teams)
        for t in teams:
            attack[t] = max(-_AB_CLAMP, min(_AB_CLAMP, attack[t] - ma))
            defence[t] = max(-_AB_CLAMP, min(_AB_CLAMP, defence[t] - md))

    if verbose:
        print(f"  Dixon-Coles fit @ {as_of}: {len(rows):,} matches, {len(teams)} "
              f"teams, mu={mu:.3f}, home_adv={gamma:.3f}")
    return GoalsModel(attack, defence, mu, gamma, rho=rho)


def fit(persist: bool = True, verbose: bool = True) -> GoalsModel:
    rows = _load_matches()
    if not rows:
        raise RuntimeError("No matches to fit on — run ingestion first.")
    model = fit_params(rows, dt.date.today(), verbose=verbose)
    if persist:
        _persist(model, verbose)
    return model


def _persist(model: GoalsModel, verbose):
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
