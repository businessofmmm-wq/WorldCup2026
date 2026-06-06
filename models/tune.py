"""
Hyperparameter tuning by held-out RPS — coordinate descent over the backtest.

Methodology (guards against overfitting the metric):
  * The leakage-free test window (2018+) is split by date into a VALIDATION slice
    (earlier) and a TEST slice (later). All searching happens on validation only;
    the winning configuration is reported once on the untouched test slice.
  * RPS is the objective (the ordered-outcome football metric); log-loss is shown
    alongside as a tie-breaker / sanity check.

We tune, in order: ensemble blend weight, Elo params (K-scale, home advantage,
draw mass, goal-diff toggle), then Dixon-Coles params (half-life, L2, rho), then
re-tune the blend. The Elo stream is cheap to recompute (one replay); the DC
stream needs a walk-forward per candidate, so its grids are kept small and it is
walked at a coarser refit cadence while searching.

Writes the winning set to data/tuned_params.json (config picks it up). Run with
`python run.py tune`.
"""
from __future__ import annotations
import datetime as dt
import json
import os

import config
from models import metrics
from models import backtest as bt

VAL_START = dt.date(2018, 1, 1)
VAL_END = dt.date(2023, 1, 1)      # validation = [2018, 2023)
TEST_END = dt.date(2100, 1, 1)     # test = [2023, now)

# Search grids.
W_GRID = [i / 20 for i in range(21)]                       # 0.00 .. 1.00
K_SCALE_GRID = [0.5, 0.7, 0.85, 1.0, 1.2, 1.4, 1.7]
HOME_ADV_GRID = [35, 50, 65, 80, 95, 110]
DRAW_MAX_GRID = [0.22, 0.26, 0.30, 0.34, 0.38, 0.42]
GD_GRID = [True, False]
HALF_LIFE_GRID = [400, 600, 900, 1300]
REG_GRID = [0.04, 0.08, 0.12, 0.18]
RHO_GRID = [-0.15, -0.08, 0.0]

# Coarser walk while searching DC (ranking params, not final numbers): bigger
# refit step + fewer warm iterations. Final test eval uses the production cadence.
TUNE_REFIT_DAYS = 120
TUNE_ITERS_WARM = 45


# --------------------------------------------------------------------------- #
# Scoring helpers
# --------------------------------------------------------------------------- #
def _blend_rps(matches, elo_probs, dc_probs, w, lo, hi, *, metric="rps"):
    rows = []
    for i, m in enumerate(matches):
        d = m[0]
        if d < lo or d >= hi or i not in dc_probs:
            continue
        ep, dp = elo_probs[i], dc_probs[i]
        en = tuple(w * ep[k] + (1.0 - w) * dp[k] for k in range(3))
        rows.append((en, metrics.outcome_index(m[3], m[4])))
    return metrics.score_stream(rows)[metric]


def _full_metrics(matches, elo_probs, dc_probs, w, lo, hi):
    rows = []
    for i, m in enumerate(matches):
        d = m[0]
        if d < lo or d >= hi or i not in dc_probs:
            continue
        ep, dp = elo_probs[i], dc_probs[i]
        en = tuple(w * ep[k] + (1.0 - w) * dp[k] for k in range(3))
        rows.append((en, metrics.outcome_index(m[3], m[4])))
    return metrics.score_stream(rows)


# --------------------------------------------------------------------------- #
# Tuning
# --------------------------------------------------------------------------- #
def run(write: bool = True) -> dict:
    matches = bt.load_matches()
    print("Loading streams (baseline Elo + DC walk-forward)...")

    elo_kw = {"k_scale": config.ELO_K_SCALE, "home_adv": config.ELO_HOME_ADVANTAGE,
              "draw_max": config.ELO_DRAW_MAX, "gd": config.ELO_USE_GD}
    dc_kw = {"half_life": config.DC_HALF_LIFE_DAYS, "reg": config.DC_REG,
             "rho": config.DC_RHO, "refit_days": TUNE_REFIT_DAYS,
             "iters_warm": TUNE_ITERS_WARM}

    elo_probs = bt.elo_replay(matches, **elo_kw)
    dc_probs = bt.dc_walkforward(matches, VAL_START, **dc_kw)

    w0 = config.ENSEMBLE_ELO_WEIGHT / (config.ENSEMBLE_ELO_WEIGHT + config.ENSEMBLE_DC_WEIGHT)
    base_val = _blend_rps(matches, elo_probs, dc_probs, w0, VAL_START, VAL_END)
    print(f"  baseline validation RPS = {base_val:.5f} (w={w0:.2f})\n")

    def val(w, ep, dp):
        return _blend_rps(matches, ep, dp, w, VAL_START, VAL_END)

    # --- 1) ensemble weight on baseline streams --------------------------- #
    w = min(W_GRID, key=lambda x: val(x, elo_probs, dc_probs))
    print(f"[1] best blend weight w_elo = {w:.2f}  (RPS {val(w, elo_probs, dc_probs):.5f})")

    # --- 2) Elo params (cheap: re-replay, blend against fixed DC) --------- #
    def elo_val(**kw):
        ep = bt.elo_replay(matches, **kw)
        return val(w, ep, dc_probs), ep

    best = dict(elo_kw)
    for _pass in range(2):
        for dim, grid in (("k_scale", K_SCALE_GRID), ("home_adv", HOME_ADV_GRID),
                          ("draw_max", DRAW_MAX_GRID), ("gd", GD_GRID)):
            scored = []
            for v in grid:
                kw = dict(best); kw[dim] = v
                r, _ = elo_val(**kw)
                scored.append((r, v))
            r, v = min(scored, key=lambda x: x[0])
            best[dim] = v
        # re-tune weight against the improved Elo stream
        elo_probs = bt.elo_replay(matches, **best)
        w = min(W_GRID, key=lambda x: val(x, elo_probs, dc_probs))
    print(f"[2] Elo: k_scale={best['k_scale']} home_adv={best['home_adv']} "
          f"draw_max={best['draw_max']} gd={best['gd']}  -> RPS {val(w, elo_probs, dc_probs):.5f} (w={w:.2f})")

    # --- 3) Dixon-Coles params (expensive: one walk per candidate) -------- #
    best_dc = dict(half_life=config.DC_HALF_LIFE_DAYS, reg=config.DC_REG, rho=config.DC_RHO)

    def dc_val(**kw):
        dp = bt.dc_walkforward(matches, VAL_START, refit_days=TUNE_REFIT_DAYS,
                               iters_warm=TUNE_ITERS_WARM, **kw)
        return val(w, elo_probs, dp), dp

    for dim, grid in (("half_life", HALF_LIFE_GRID), ("reg", REG_GRID), ("rho", RHO_GRID)):
        scored = []
        for v in grid:
            kw = dict(best_dc); kw[dim] = v
            r, _ = dc_val(**kw)
            scored.append((r, v))
            print(f"      DC {dim}={v}: RPS {r:.5f}")
        r, v = min(scored, key=lambda x: x[0])
        best_dc[dim] = v
    dc_probs = bt.dc_walkforward(matches, VAL_START, refit_days=TUNE_REFIT_DAYS,
                                 iters_warm=TUNE_ITERS_WARM, **best_dc)
    print(f"[3] DC: half_life={best_dc['half_life']} reg={best_dc['reg']} rho={best_dc['rho']}")

    # --- 4) final blend re-tune ------------------------------------------- #
    w = min(W_GRID, key=lambda x: val(x, elo_probs, dc_probs))
    final_val = val(w, elo_probs, dc_probs)
    print(f"[4] final blend w_elo = {w:.2f}  validation RPS {final_val:.5f} "
          f"(baseline {base_val:.5f}, {100*(base_val-final_val)/base_val:+.1f}%)\n")

    params = {
        "ELO_K_SCALE": best["k_scale"], "ELO_HOME_ADVANTAGE": float(best["home_adv"]),
        "ELO_DRAW_MAX": best["draw_max"], "ELO_USE_GD": bool(best["gd"]),
        "DC_HALF_LIFE_DAYS": float(best_dc["half_life"]), "DC_REG": best_dc["reg"],
        "DC_RHO": best_dc["rho"],
        "ENSEMBLE_ELO_WEIGHT": round(w, 4), "ENSEMBLE_DC_WEIGHT": round(1.0 - w, 4),
    }

    # --- held-out TEST evaluation (refit at the production cadence) ------- #
    print("Evaluating on held-out TEST slice (2023+, refit 45d)...")
    elo_final = bt.elo_replay(matches, k_scale=params["ELO_K_SCALE"],
                              home_adv=params["ELO_HOME_ADVANTAGE"],
                              draw_max=params["ELO_DRAW_MAX"], gd=params["ELO_USE_GD"])
    dc_final = bt.dc_walkforward(matches, VAL_END, refit_days=45,
                                 half_life=params["DC_HALF_LIFE_DAYS"],
                                 reg=params["DC_REG"], rho=params["DC_RHO"])
    dc_base = bt.dc_walkforward(matches, VAL_END, refit_days=45)
    elo_base = bt.elo_replay(matches)
    m_base = _full_metrics(matches, elo_base, dc_base, w0, VAL_END, TEST_END)
    m_tuned = _full_metrics(matches, elo_final, dc_final, w, VAL_END, TEST_END)
    print(f"  {'':<10}{'N':>7}{'RPS':>9}{'LogLoss':>10}{'Brier':>9}{'Acc':>8}")
    print(f"  {'baseline':<10}{m_base['n']:>7}{m_base['rps']:>9.4f}"
          f"{m_base['log_loss']:>10.4f}{m_base['brier']:>9.4f}{m_base['acc']:>8.3f}")
    print(f"  {'tuned':<10}{m_tuned['n']:>7}{m_tuned['rps']:>9.4f}"
          f"{m_tuned['log_loss']:>10.4f}{m_tuned['brier']:>9.4f}{m_tuned['acc']:>8.3f}")
    gain = 100 * (m_base['rps'] - m_tuned['rps']) / m_base['rps']
    print(f"  test-RPS change: {gain:+.1f}%\n")

    if write and m_tuned['rps'] <= m_base['rps']:
        with open(os.path.join(config.DATA_DIR, "tuned_params.json"), "w",
                  encoding="utf-8") as fh:
            json.dump(params, fh, indent=1)
        print(f"Wrote tuned_params.json:\n{json.dumps(params, indent=1)}")
    elif write:
        print("Tuned config did NOT beat baseline on the test slice — not writing.")
    return {"params": params, "test_base": m_base, "test_tuned": m_tuned}


def _temper(p, t):
    if t == 1.0:
        return p
    inv = 1.0 / t
    q = [max(p[k], 1e-9) ** inv for k in range(3)]
    s = sum(q)
    return tuple(x / s for x in q)


def calibrate(write: bool = True) -> float:
    """Fit the ensemble temperature on validation; report held-out effect.

    Uses the production model structure (ordered-logit draw model + the tuned
    Dixon-Coles/blend). The draw model is fit leakage-free for each slice. Merges
    ENSEMBLE_TEMPERATURE into data/tuned_params.json.
    """
    from models import draw_model
    matches = bt.load_matches()
    w = config.ENSEMBLE_ELO_WEIGHT
    elo_kw = dict(k_scale=config.ELO_K_SCALE, home_adv=config.ELO_HOME_ADVANTAGE,
                  gd=config.ELO_USE_GD)

    # leakage-free ordered draw models: one trained < VAL_START, one < VAL_END
    dm_v = draw_model.fit(samples=draw_model.collect_samples(upto=VAL_START),
                          persist=False, verbose=False)
    dm_t = draw_model.fit(samples=draw_model.collect_samples(upto=VAL_END),
                          persist=False, verbose=False)
    elo_v = bt.elo_replay(matches, draw_fn=lambda d, n: draw_model.probs(d, *dm_v), **elo_kw)
    elo_t = bt.elo_replay(matches, draw_fn=lambda d, n: draw_model.probs(d, *dm_t), **elo_kw)
    dc = bt.dc_walkforward(matches, VAL_START, refit_days=45)

    def stream(elo_probs, lo, hi):
        out = []
        for i, m in enumerate(matches):
            if m[0] < lo or m[0] >= hi or i not in dc:
                continue
            en = tuple(w * elo_probs[i][k] + (1 - w) * dc[i][k] for k in range(3))
            out.append((en, metrics.outcome_index(m[3], m[4])))
        return out

    val = stream(elo_v, VAL_START, VAL_END)
    test = stream(elo_t, VAL_END, TEST_END)
    best_t, best_ll = 1.0, metrics.score_stream(val)["log_loss"]
    t = 0.60
    while t <= 1.61:
        ll = metrics.score_stream([(_temper(p, t), o) for p, o in val])["log_loss"]
        if ll < best_ll:
            best_ll, best_t = ll, round(t, 2)
        t = round(t + 0.05, 2)

    m1 = metrics.score_stream(test)
    mT = metrics.score_stream([(_temper(p, best_t), o) for p, o in test])
    print(f"Temperature: best T = {best_t} (validation log-loss {best_ll:.4f})")
    print(f"  held-out TEST  T=1.00 : RPS {m1['rps']:.4f}  LogLoss {m1['log_loss']:.4f}  Brier {m1['brier']:.4f}")
    print(f"  held-out TEST  T={best_t:<4}: RPS {mT['rps']:.4f}  LogLoss {mT['log_loss']:.4f}  Brier {mT['brier']:.4f}")

    if write and mT["log_loss"] <= m1["log_loss"]:
        path = os.path.join(config.DATA_DIR, "tuned_params.json")
        params = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                params = json.load(fh)
        params["ENSEMBLE_TEMPERATURE"] = best_t
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(params, fh, indent=1)
        print(f"  wrote ENSEMBLE_TEMPERATURE={best_t} to tuned_params.json")
    elif write:
        print("  temperature did not help on the held-out slice — leaving T=1.0")
    return best_t


if __name__ == "__main__":
    run()
