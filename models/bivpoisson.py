"""
Bivariate-Poisson goals model (pure Python, no numpy/scipy).

A *proper* joint distribution for the scoreline, as an upgrade over the
Dixon-Coles low-score correction in models/poisson.py. Where Dixon-Coles keeps
two independent Poissons and multiplies four cells (0-0/1-0/0-1/1-1) by an
ad-hoc factor tau, the bivariate Poisson is a genuine bivariate law with a
shared latent component (Karlis & Ntzoufras, 2003):

    W1 ~ Poisson(l1),  W2 ~ Poisson(l2),  W3 ~ Poisson(l3),  independent
    home goals  X = W1 + W3
    away goals  Y = W2 + W3

so X ~ Poisson(l1+l3), Y ~ Poisson(l2+l3) and, crucially, Cov(X, Y) = l3. The
shared term l3 is the common "match tempo" both sides ride (an open, end-to-end
game lifts both scores; a cagey one suppresses both). The joint pmf is

    P(X=x, Y=y) = e^-(l1+l2+l3) * l1^x/x! * l2^y/y!
                  * SUM_{k=0}^{min(x,y)} C(x,k) C(y,k) k! (l3 / (l1 l2))^k

which reduces to two independent Poissons exactly when l3 = 0.

Design — we *reuse* the Dixon-Coles marginal fit (models/poisson.fit_params:
the same time-decayed attack/defence MLE) for the per-match means, since those
means are exactly E[X] = l1+l3 and E[Y] = l2+l3. We then split off a single
global covariance l3, fit by 1-D maximum likelihood over the same matches, and
set l1 = E[X]-l3, l2 = E[Y]-l3 per fixture. Net effect: identical expected goals
to Dixon-Coles, but a real correlated joint — so the 1X2 (especially the draw
mass) comes from the whole grid, not a four-cell patch.

Honest caveat baked into the maths: l3 >= 0, so a bivariate Poisson can only
represent *positive* goal correlation. If the data wants negative dependence
(international football often sits near zero / slightly negative), the MLE drives
l3 -> 0 and this collapses to an independent double-Poisson. That is the correct
outcome, and the backtest (run.py backtest --compare) is what adjudicates whether
it beats the Dixon-Coles tau on held-out RPS. Nothing here is assumed; it is
measured.

BivariatePoissonModel subclasses GoalsModel and overrides only scoreline_grid,
so predict()/expected_goals() and every downstream consumer (tournament sim,
dashboard, exporter) work unchanged — it is a drop-in goals model.
"""
from __future__ import annotations
import math
import os
import json
import datetime as dt

import config
from db import connect
from models import poisson as poisson_mod
from models.poisson import GoalsModel

_PARAMS_FILE = os.path.join(config.DATA_DIR, "bivpois_params.json")


# --------------------------------------------------------------------------- #
# Bivariate-Poisson pmf (log space for stability in the fit)
# --------------------------------------------------------------------------- #
def _bp_logpmf(x: int, y: int, l1: float, l2: float, l3: float) -> float:
    """log P(X=x, Y=y) under the shared-component bivariate Poisson.

    Computed in log space: the convolution sum S >= 1 (its k=0 term is 1 and
    every term is non-negative because l3 >= 0), so log(S) is well defined and
    the factorials go through math.lgamma — no overflow on high scorelines.
    """
    l1 = l1 if l1 > 1e-9 else 1e-9
    l2 = l2 if l2 > 1e-9 else 1e-9
    if l3 > 0.0:
        ratio = l3 / (l1 * l2)
        s = 0.0
        for k in range(min(x, y) + 1):
            s += math.comb(x, k) * math.comb(y, k) * math.factorial(k) * ratio ** k
    else:
        s = 1.0   # independent double-Poisson limit
    return (-(l1 + l2 + l3)
            + x * math.log(l1) - math.lgamma(x + 1)
            + y * math.log(l2) - math.lgamma(y + 1)
            + math.log(s))


def _bp_pmf(x: int, y: int, l1: float, l2: float, l3: float) -> float:
    return math.exp(_bp_logpmf(x, y, l1, l2, l3))


# --------------------------------------------------------------------------- #
# Model
# --------------------------------------------------------------------------- #
class BivariatePoissonModel(GoalsModel):
    """A GoalsModel whose scoreline grid is a bivariate Poisson.

    Holds the Dixon-Coles marginals (attack/defence/mu/gamma) plus one global
    covariance `lam3`. expected_goals() is inherited unchanged: it returns the
    marginal means E[X], E[Y], which here equal l1+l3 and l2+l3.
    """

    def __init__(self, attack, defence, mu, gamma, lam3: float):
        super().__init__(attack, defence, mu, gamma)
        self.lam3 = max(0.0, lam3)

    def scoreline_grid(self, home: str, away: str, neutral: bool = True,
                       max_goals: int | None = None):
        max_goals = max_goals or config.DC_MAX_GOALS
        mean_h, mean_a = self.expected_goals(home, away, neutral)   # = l1+l3, l2+l3
        # Keep the (well-fit) marginal means and carve out the shared component;
        # never let l1/l2 go non-positive for a very low-scoring fixture.
        l3 = min(self.lam3, mean_h - 1e-6, mean_a - 1e-6)
        l3 = l3 if l3 > 0.0 else 0.0
        l1, l2 = mean_h - l3, mean_a - l3
        grid = [[0.0] * (max_goals + 1) for _ in range(max_goals + 1)]
        total = 0.0
        for i in range(max_goals + 1):
            for j in range(max_goals + 1):
                p = _bp_pmf(i, j, l1, l2, l3)
                grid[i][j] = p
                total += p
        if total > 0:   # renormalise the truncated-grid mass back to 1
            for i in range(max_goals + 1):
                for j in range(max_goals + 1):
                    grid[i][j] /= total
        return grid, mean_h, mean_a


# --------------------------------------------------------------------------- #
# Fitting the shared covariance l3 (1-D MLE, given the DC marginals)
# --------------------------------------------------------------------------- #
def _golden_min(f, lo: float, hi: float, tol: float = 1e-4, iters: int = 60):
    """Golden-section minimiser of a unimodal f on [lo, hi]. Returns the argmin.

    Robust at the boundary: if the optimum is l3=0 (no positive correlation
    supported) the bracket simply converges down to lo.
    """
    invphi = (math.sqrt(5) - 1) / 2          # 1/phi  ~ 0.618
    invphi2 = (3 - math.sqrt(5)) / 2         # 1/phi^2
    a, b = lo, hi
    h = b - a
    c, d = a + invphi2 * h, a + invphi * h
    fc, fd = f(c), f(d)
    for _ in range(iters):
        if h < tol:
            break
        if fc < fd:
            b, d, fd = d, c, fc
            h *= invphi
            c = a + invphi2 * h
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            h *= invphi
            d = a + invphi * h
            fd = f(d)
    return (a + b) / 2


def fit_lambda3(base: GoalsModel, data, as_of: dt.date, *,
                half_life: float | None = None,
                cap: float | None = None, verbose: bool = False) -> float:
    """MLE the single global covariance l3 >= 0, holding the DC marginals fixed.

    `data` is the same (date, home, away, hs, as, neutral) rows the DC fit used;
    weights are the identical exponential time-decay anchored at `as_of`, so the
    estimate is leakage-free in a walk-forward (only matches before `as_of`).
    """
    half_life = config.DC_HALF_LIFE_DAYS if half_life is None else half_life
    cap = config.BP_MAX_LAMBDA3 if cap is None else cap

    rows = []   # (x, y, mean_h, mean_a, weight, const) with const = lgamma terms
    for d, home, away, hs, as_, neutral in data:
        age = (as_of - d).days
        if age < 0:
            continue
        w = 0.5 ** (age / half_life)
        mh, ma = base.expected_goals(home, away, neutral)
        rows.append((hs, as_, mh, ma, w))
    if not rows:
        return 0.0

    def nll(l3: float) -> float:
        tot = 0.0
        for hs, as_, mh, ma, w in rows:
            l1 = mh - l3
            l2 = ma - l3
            if l1 < 1e-6:
                l1 = 1e-6
            if l2 < 1e-6:
                l2 = 1e-6
            tot -= w * _bp_logpmf(hs, as_, l1, l2, l3)
        return tot

    lam3 = _golden_min(nll, 0.0, cap)
    if lam3 < 1e-3:          # snap a negligible covariance to exactly zero
        lam3 = 0.0
    if verbose:
        base_nll = nll(0.0)
        print(f"  bivariate-Poisson fit @ {as_of}: {len(rows):,} matches, "
              f"lambda3={lam3:.4f} (independent NLL {base_nll:,.1f} -> "
              f"{nll(lam3):,.1f})")
    return lam3


# --------------------------------------------------------------------------- #
# Train / persist / load
# --------------------------------------------------------------------------- #
def fit(base: GoalsModel | None = None, persist: bool = True,
        verbose: bool = True) -> BivariatePoissonModel:
    """Fit the bivariate-Poisson model: DC marginals + the global l3.

    `base` lets the trainer pass an already-fit Dixon-Coles model so we do not
    refit the attack/defence twice; if omitted we fit the marginals ourselves.
    """
    data = poisson_mod._load_matches()
    if not data:
        raise RuntimeError("No matches to fit on — run ingestion first.")
    if base is None:
        base = poisson_mod.fit_params(data, dt.date.today(), verbose=verbose)
    lam3 = fit_lambda3(base, data, dt.date.today(), verbose=verbose)
    model = BivariatePoissonModel(base.attack, base.defence, base.mu,
                                  base.gamma, lam3)
    if persist:
        _persist(lam3, verbose)
    return model


def _persist(lam3: float, verbose: bool = True) -> None:
    with open(_PARAMS_FILE, "w", encoding="utf-8") as fh:
        json.dump({"lambda3": lam3, "fitted_at": dt.date.today().isoformat()}, fh)
    if verbose:
        print(f"  persisted lambda3={lam3:.4f} -> {os.path.basename(_PARAMS_FILE)}")


def load() -> BivariatePoissonModel:
    """Rebuild from the persisted DC marginals + the saved l3 (skips refitting)."""
    base = poisson_mod.load()
    lam3 = config.BP_LAMBDA3_FALLBACK
    try:
        with open(_PARAMS_FILE, encoding="utf-8") as fh:
            lam3 = float(json.load(fh)["lambda3"])
    except (FileNotFoundError, KeyError, ValueError):
        pass
    return BivariatePoissonModel(base.attack, base.defence, base.mu,
                                 base.gamma, lam3)


if __name__ == "__main__":
    m = fit()
    dc = poisson_mod.load()
    print(f"\n  fitted shared covariance lambda3 = {m.lam3:.4f}\n")
    print("  fixture            BP H/D/A            DC H/D/A           draw shift")
    for h, a in [("Brazil", "Argentina"), ("France", "England"),
                 ("Spain", "Germany"), ("United States", "Mexico")]:
        pb = m.predict(h, a, neutral=True)
        pd = dc.predict(h, a, neutral=True)
        print(f"  {h[:8]:>8}-{a[:8]:<8}  "
              f"{pb['p_home']:.0%}/{pb['p_draw']:.0%}/{pb['p_away']:.0%}   "
              f"vs  {pd['p_home']:.0%}/{pd['p_draw']:.0%}/{pd['p_away']:.0%}   "
              f"{(pb['p_draw'] - pd['p_draw']) * 100:+.1f} pp")
