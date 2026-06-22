"""
Leakage-free walk-forward backtest for the match models.

This is the measurement foundation: without it, "most accurate" is unfalsifiable.
For every finished international in a held-out test window we produce the
prediction the engine *would* have made knowing only what happened before that
match, then score it (RPS / log-loss / Brier / accuracy / calibration).

Two honest streams, aligned per match:

  * Elo — replayed chronologically over all history; the prediction for each
    match is read off the ratings as they stand BEFORE that match is folded in
    (predict-before-update). Naturally leakage-free in a single pass.

  * Dixon-Coles — a batch MLE fit, so it is refit periodically (`refit_days`)
    across the test window. Each refit (`poisson.fit_params`) is anchored at its
    as-of date and only ever sees matches strictly before it, with the time-decay
    clock reset to that date. Refits warm-start from the previous fit, so the
    whole walk stays fast.

The ensemble simply blends the two aligned 1X2 vectors. Naive baselines (uniform
and the pre-test base rate, split by neutral) are scored too, so we can see how
much real signal the models add.
"""
from __future__ import annotations
import datetime as dt

import config
from db import connect
from models import metrics
from models.elo import _k_for, _gd_multiplier
from models import poisson as poisson_mod

ELO_START = config.ELO_START
_DRAW_MAX = 0.30  # mirrors predict._DRAW_MAX (Elo closeness -> draw mass)


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
def load_matches() -> list[tuple]:
    """All finished matches, chronological: (date, home, away, hs, as, tourn, neutral)."""
    with connect() as conn:
        return conn.execute(
            """
            SELECT match_date, home_team, away_team, home_score, away_score,
                   tournament, neutral
            FROM matches
            WHERE status='finished' AND home_score IS NOT NULL
                  AND away_score IS NOT NULL
            ORDER BY match_date, id
            """
        ).fetchall()


# --------------------------------------------------------------------------- #
# Elo stream (predict-before-update, parametrised for tuning)
# --------------------------------------------------------------------------- #
def _elo_1x2(ra: float, rb: float, neutral: bool, home_adv: float,
             draw_max: float) -> tuple[float, float, float]:
    """1X2 from two Elo ratings — identical maths to predict.elo_1x2."""
    ha = 0.0 if neutral else home_adv
    e = 1.0 / (1.0 + 10 ** ((rb - ra - ha) / 400.0))
    p_draw = max(0.0, draw_max * (1.0 - 2.0 * abs(e - 0.5)))
    p_home = max(0.0, e - 0.5 * p_draw)
    p_away = max(0.0, (1.0 - e) - 0.5 * p_draw)
    s = p_home + p_draw + p_away
    return (p_home / s, p_draw / s, p_away / s)


def elo_replay(matches: list[tuple], *, k_scale: float = config.ELO_K_SCALE,
               home_adv: float = config.ELO_HOME_ADVANTAGE,
               draw_max: float = config.ELO_DRAW_MAX, gd: bool = True,
               draw_fn=None) -> list[tuple]:
    """Replay all matches; return a per-match Elo 1X2 aligned to `matches`.

    `draw_fn(elo_diff, neutral) -> (ph, pd, pa)` overrides the built-in closeness
    draw model when supplied (used by the empirical draw model in Phase 2).
    """
    elo: dict[str, float] = {}
    probs: list[tuple] = []
    for d, home, away, hs, as_, tourn, neutral in matches:
        ra = elo.get(home, ELO_START)
        rb = elo.get(away, ELO_START)
        if draw_fn is not None:
            diff = (ra + (0.0 if neutral else home_adv)) - rb
            probs.append(draw_fn(diff, neutral))
        else:
            probs.append(_elo_1x2(ra, rb, neutral, home_adv, draw_max))
        # fold the result in (post-prediction) — this is the update step
        ha = 0.0 if neutral else home_adv
        exp_home = 1.0 / (1.0 + 10 ** ((rb - ra - ha) / 400.0))
        sh = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
        mult = _gd_multiplier(hs - as_) if gd else 1.0
        k = _k_for(tourn) * k_scale * mult
        delta = k * (sh - exp_home)
        elo[home] = ra + delta
        elo[away] = rb - delta
    return probs


# --------------------------------------------------------------------------- #
# Dixon-Coles walk-forward
# --------------------------------------------------------------------------- #
def dc_walkforward(matches: list[tuple], test_start: dt.date, *,
                   refit_days: int = 45, recent_years: int = config.DC_RECENT_YEARS,
                   half_life: float = config.DC_HALF_LIFE_DAYS,
                   reg: float = config.DC_REG, rho: float = config.DC_RHO,
                   iters_cold: int = config.DC_ITERS, iters_warm: int = 60,
                   warm: bool = True) -> dict[int, tuple]:
    """Honest DC 1X2 for every test match: {match_index: (ph, pd, pa)}.

    Refits at most every `refit_days`; each fit sees only matches strictly before
    its as-of date. Returns a dict keyed by the match's index in `matches`.
    """
    dc_rows = [(d, h, a, hs, as_, neu) for d, h, a, hs, as_, tourn, neu in matches]
    out: dict[int, tuple] = {}
    model = None
    next_refit = test_start
    for i, (d, home, away, hs, as_, tourn, neutral) in enumerate(matches):
        if d < test_start:
            continue
        if model is None or d >= next_refit:
            lo = d - dt.timedelta(days=365 * recent_years)
            window = [r for r in dc_rows if lo <= r[0] < d]
            model = poisson_mod.fit_params(
                window, d, half_life=half_life, reg=reg, rho=rho,
                iters=(iters_cold if model is None else iters_warm),
                init=(model if warm else None))
            next_refit = d + dt.timedelta(days=refit_days)
        pr = model.predict(home, away, neutral=neutral)
        out[i] = (pr["p_home"], pr["p_draw"], pr["p_away"])
    return out


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #
def base_rates(matches: list[tuple], test_start: dt.date) -> dict[bool, tuple]:
    """Empirical H/D/A split from PRE-test matches, keyed by neutral flag."""
    agg = {False: [0, 0, 0, 0], True: [0, 0, 0, 0]}  # [H, D, A, N]
    for d, home, away, hs, as_, tourn, neutral in matches:
        if d >= test_start:
            break
        o = metrics.outcome_index(hs, as_)
        agg[bool(neutral)][o] += 1
        agg[bool(neutral)][3] += 1
    rates = {}
    for neu, (h, dr, a, n) in agg.items():
        n = n or 1
        rates[neu] = (h / n, dr / n, a / n)
    return rates


# --------------------------------------------------------------------------- #
# Assemble + score
# --------------------------------------------------------------------------- #
def _temper(p, t):
    if t == 1.0:
        return p
    inv = 1.0 / t
    q = [max(p[k], 1e-9) ** inv for k in range(3)]
    s = sum(q)
    return tuple(x / s for x in q)


def build_streams(matches, test_start, *, ensemble_weight=None,
                  elo_kw=None, dc_kw=None, temperature=None) -> dict:
    """Run both models and return aligned per-match streams over the test window.

    Each stream is a list of (date, neutral, probs, outcome). `ensemble_weight`
    is the Elo weight w (DC weight = 1-w); defaults to the config blend. The
    ensemble stream has the calibration `temperature` applied (production-faithful).
    """
    if ensemble_weight is None:
        we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
        ensemble_weight = we / (we + wd)
    if temperature is None:
        temperature = config.ENSEMBLE_TEMPERATURE
    w = ensemble_weight
    elo_probs = elo_replay(matches, **(elo_kw or {}))
    dc_probs = dc_walkforward(matches, test_start, **(dc_kw or {}))
    rates = base_rates(matches, test_start)
    # Pi-ratings online replay (predict-before-update => leakage-free), only when on.
    wp = getattr(config, "ENSEMBLE_PI_WEIGHT", 0.0)
    pi_probs = None
    if wp:
        from models import pirating
        _pr = pirating.PiRatings()
        pi_probs = {}
        for _i, (_d, _h, _a, _hs, _as, _t, _neu) in enumerate(matches):
            if _d >= test_start:
                _g = _pr.expected_gd(_h, _a, bool(_neu))
                _pp = pirating.gd_to_1x2(_g)
                pi_probs[_i] = (_pp["p_home"], _pp["p_draw"], _pp["p_away"])
            _pr.update(_h, _a, _hs, _as, neutral=bool(_neu))

    elo_s, dc_s, ens_s, base_s, unif_s, enspi_s = [], [], [], [], [], []
    for i, (d, home, away, hs, as_, tourn, neutral) in enumerate(matches):
        if d < test_start or i not in dc_probs:
            continue
        o = metrics.outcome_index(hs, as_)
        ep = elo_probs[i]
        dp = dc_probs[i]
        base_pre = tuple(w * ep[k] + (1.0 - w) * dp[k] for k in range(3))
        en = _temper(base_pre, temperature)
        elo_s.append((d, neutral, ep, o))
        dc_s.append((d, neutral, dp, o))
        ens_s.append((d, neutral, en, o))
        base_s.append((d, neutral, rates[bool(neutral)], o))
        unif_s.append((d, neutral, (1 / 3, 1 / 3, 1 / 3), o))
        if pi_probs is not None and i in pi_probs:
            pp = pi_probs[i]
            mp = tuple((1.0 - wp) * base_pre[k] + wp * pp[k] for k in range(3))
            sm = sum(mp) or 1.0
            enspi_s.append((d, neutral, _temper(tuple(x / sm for x in mp), temperature), o))
    out = {"elo": elo_s, "dc": dc_s, "ensemble": ens_s,
           "base_rate": base_s, "uniform": unif_s}
    if enspi_s:
        out["ensemble_pi"] = enspi_s
    return out


def _pairs(stream, lo=None, hi=None):
    """Extract (probs, outcome), optionally restricted to a [lo, hi) date slice."""
    out = []
    for d, neutral, p, o in stream:
        if lo is not None and d < lo:
            continue
        if hi is not None and d >= hi:
            continue
        out.append((p, o))
    return out


def report(test_start: dt.date | None = None, refit_days: int = 45) -> dict:
    """Run the baseline backtest and print the metrics table. Returns streams."""
    if test_start is None:
        test_start = dt.date(2018, 1, 1)
    print(f"Backtest - test window from {test_start} (DC refit every {refit_days}d)\n")
    matches = load_matches()
    # Production-faithful Elo 1X2: ordered-logit draw model, fit leakage-free on
    # matches strictly before the test window (falls back to the linear model if
    # the draw model can't be fit).
    elo_kw = {}
    try:
        from models import draw_model
        params = draw_model.fit(samples=draw_model.collect_samples(upto=test_start),
                                persist=False, verbose=False)
        elo_kw["draw_fn"] = lambda d, n: draw_model.probs(d, *params)
    except Exception:
        pass
    streams = build_streams(matches, test_start, elo_kw=elo_kw,
                            dc_kw={"refit_days": refit_days})

    order = ["uniform", "base_rate", "elo", "dc", "ensemble"]
    if streams.get("ensemble_pi"):
        order.append("ensemble_pi")
    label = {"uniform": "Uniform (1/3)", "base_rate": "Base rate",
             "elo": "Elo", "dc": "Dixon-Coles", "ensemble": "Ensemble",
             "ensemble_pi": "Ensemble + pi"}
    print(f"  {'Model':<16}{'N':>7}{'RPS':>9}{'LogLoss':>10}{'Brier':>9}{'Acc':>8}")
    print("  " + "-" * 58)
    results = {}
    for key in order:
        m = metrics.score_stream(_pairs(streams[key]))
        results[key] = m
        print(f"  {label[key]:<16}{m['n']:>7}{m['rps']:>9.4f}"
              f"{m['log_loss']:>10.4f}{m['brier']:>9.4f}{m['acc']:>8.3f}")
    print()
    # calibration of the ensemble (home class) + overall reliability error
    ece = metrics.reliability_error(_pairs(streams["ensemble"]))
    print(f"  Ensemble calibration error (mean abs, 3 classes): {ece:.4f}")
    print("  Ensemble reliability (home win):")
    print(f"    {'pred-bin':<14}{'mean_pred':>10}{'emp_freq':>10}{'n':>8}")
    for lo, hi, mp, ef, n in metrics.calibration(_pairs(streams["ensemble"]), cls=metrics.HOME):
        print(f"    {f'{lo:.1f}-{hi:.1f}':<14}{mp:>10.3f}{ef:>10.3f}{n:>8}")
    return {"streams": streams, "results": results, "test_start": test_start}


# --------------------------------------------------------------------------- #
# Goals-model comparison: bivariate Poisson vs Dixon-Coles (head-to-head)
# --------------------------------------------------------------------------- #
def _goals_walk_both(matches, test_start, lam3, diag_factor=1.0, *, refit_days=45,
                     recent_years=config.DC_RECENT_YEARS,
                     half_life=config.DC_HALF_LIFE_DAYS, reg=config.DC_REG,
                     rho=config.DC_RHO, iters_cold=config.DC_ITERS,
                     iters_warm=60, warm=True):
    """One leakage-free walk-forward, three predictions per test match.

    Refits the shared Dixon-Coles attack/defence exactly as `dc_walkforward`
    does, then reads off DC, BP (shared covariance `lam3`) and diagonal-inflated
    BP (`diag_factor`) 1X2s per match. One refit serves all three — they share
    the same marginals. Returns (dc_out, bp_out, dibp_out).
    """
    from models import bivpoisson as bp
    dc_rows = [(d, h, a, hs, as_, neu) for d, h, a, hs, as_, tourn, neu in matches]
    dc_out: dict[int, tuple] = {}
    bp_out: dict[int, tuple] = {}
    dibp_out: dict[int, tuple] = {}
    model = bpm = dibpm = None
    next_refit = test_start
    for i, (d, home, away, hs, as_, tourn, neutral) in enumerate(matches):
        if d < test_start:
            continue
        if model is None or d >= next_refit:
            lo = d - dt.timedelta(days=365 * recent_years)
            window = [r for r in dc_rows if lo <= r[0] < d]
            model = poisson_mod.fit_params(
                window, d, half_life=half_life, reg=reg, rho=rho,
                iters=(iters_cold if model is None else iters_warm),
                init=(model if warm else None))
            bpm = bp.BivariatePoissonModel(model.attack, model.defence,
                                           model.mu, model.gamma, lam3)
            dibpm = bp.DiagonalInflatedBivariatePoissonModel(
                model.attack, model.defence, model.mu, model.gamma,
                lam3, diag_factor)
            next_refit = d + dt.timedelta(days=refit_days)
        pd_ = model.predict(home, away, neutral=neutral)
        pb_ = bpm.predict(home, away, neutral=neutral)
        pdb_ = dibpm.predict(home, away, neutral=neutral)
        dc_out[i] = (pd_["p_home"], pd_["p_draw"], pd_["p_away"])
        bp_out[i] = (pb_["p_home"], pb_["p_draw"], pb_["p_away"])
        dibp_out[i] = (pdb_["p_home"], pdb_["p_draw"], pdb_["p_away"])
    return dc_out, bp_out, dibp_out


def compare(test_start: dt.date | None = None, refit_days: int = 45) -> dict:
    """Score bivariate-Poisson against Dixon-Coles (and each blended with Elo).

    The shared covariance lambda3 is MLE-fit once on matches strictly BEFORE the
    test window (leakage-free), then held across the walk. Prints an RPS/LogLoss/
    Brier/Acc table for Elo, DC, BP and both ensembles; returns the metrics.
    """
    from models import bivpoisson as bp
    if test_start is None:
        test_start = dt.date(2018, 1, 1)
    matches = load_matches()

    # lambda3 and diagonal_factor from pre-test data only (honest walk-forward).
    lo = test_start - dt.timedelta(days=365 * config.DC_RECENT_YEARS)
    pre = [(d, h, a, hs, as_, neu)
           for d, h, a, hs, as_, tourn, neu in matches if lo <= d < test_start]
    base = poisson_mod.fit_params(pre, test_start)
    lam3 = bp.fit_lambda3(base, pre, test_start, verbose=True)
    bpm_pre = bp.BivariatePoissonModel(base.attack, base.defence, base.mu,
                                       base.gamma, lam3)
    diag_factor = bp.fit_diagonal_factor(bpm_pre, pre, test_start, verbose=True)
    print(f"\nGoals-model compare — test from {test_start} "
          f"(DC refit every {refit_days}d, "
          f"lambda3={lam3:.4f}, diag_factor={diag_factor:.4f})\n")

    dc_probs, bp_probs, dibp_probs = _goals_walk_both(
        matches, test_start, lam3, diag_factor, refit_days=refit_days)
    # Production-faithful Elo (empirical draw model fit pre-test), as in report().
    elo_kw = {}
    try:
        from models import draw_model
        params = draw_model.fit(samples=draw_model.collect_samples(upto=test_start),
                                persist=False, verbose=False)
        elo_kw["draw_fn"] = lambda d, n: draw_model.probs(d, *params)
    except Exception:
        pass
    elo_probs = elo_replay(matches, **elo_kw)

    we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
    w = we / (we + wd)
    temp = config.ENSEMBLE_TEMPERATURE
    pairs: dict[str, list] = {k: [] for k in
                              ("elo", "dc", "bp", "dibp", "ens_dc", "ens_bp", "ens_dibp")}
    for i, (d, home, away, hs, as_, tourn, neutral) in enumerate(matches):
        if d < test_start or i not in dc_probs:
            continue
        o = metrics.outcome_index(hs, as_)
        ep, dp, bpp, dibpp = elo_probs[i], dc_probs[i], bp_probs[i], dibp_probs[i]
        en_dc = _temper(tuple(w * ep[k] + (1 - w) * dp[k] for k in range(3)), temp)
        en_bp = _temper(tuple(w * ep[k] + (1 - w) * bpp[k] for k in range(3)), temp)
        en_dibp = _temper(tuple(w * ep[k] + (1 - w) * dibpp[k] for k in range(3)), temp)
        pairs["elo"].append((ep, o))
        pairs["dc"].append((dp, o))
        pairs["bp"].append((bpp, o))
        pairs["dibp"].append((dibpp, o))
        pairs["ens_dc"].append((en_dc, o))
        pairs["ens_bp"].append((en_bp, o))
        pairs["ens_dibp"].append((en_dibp, o))

    order = ["elo", "dc", "bp", "dibp", "ens_dc", "ens_bp", "ens_dibp"]
    label = {"elo": "Elo", "dc": "Dixon-Coles", "bp": "Bivariate-Poisson",
             "dibp": "Diagonal-Inflated BP",
             "ens_dc": "Ensemble (Elo+DC)", "ens_bp": "Ensemble (Elo+BP)",
             "ens_dibp": "Ensemble (Elo+DiBP)"}
    print(f"  {'Model':<22}{'N':>7}{'RPS':>9}{'LogLoss':>10}{'Brier':>9}{'Acc':>8}")
    print("  " + "-" * 65)
    results = {}
    for key in order:
        m = metrics.score_stream(pairs[key])
        results[key] = m
        print(f"  {label[key]:<22}{m['n']:>7}{m['rps']:>9.4f}"
              f"{m['log_loss']:>10.4f}{m['brier']:>9.4f}{m['acc']:>8.3f}")
    d_rps_bp = results["bp"]["rps"] - results["dc"]["rps"]
    d_rps_dibp = results["dibp"]["rps"] - results["dc"]["rps"]
    d_ens_bp = results["ens_bp"]["rps"] - results["ens_dc"]["rps"]
    d_ens_dibp = results["ens_dibp"]["rps"] - results["ens_dc"]["rps"]
    print(f"\n  BP - DC RPS (goals only):   {d_rps_bp:+.5f}"
          f"   |   in ensemble: {d_ens_bp:+.5f}   (negative = better)")
    print(f"  DiBP - DC RPS (goals):      {d_rps_dibp:+.5f}"
          f"   |   in ensemble: {d_ens_dibp:+.5f}   (negative = better)")
    return {"results": results, "lam3": lam3, "diag_factor": diag_factor,
            "test_start": test_start}


if __name__ == "__main__":
    report()
