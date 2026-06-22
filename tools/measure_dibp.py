"""Tune the diagonal-inflation factor against held-out RPS (not just likelihood).
DiBP(f) is a closed-form transform of the base BP 1X2: inflate draw mass by f and
renormalise, Z = 1 - p_draw + f*p_draw. So we walk BP once and sweep f cheaply.
Leakage-free: factor fit on 2018..2022, evaluated on 2022+."""
from __future__ import annotations
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from models import backtest, metrics, poisson as pois, draw_model
from models import bivpoisson as bp

T0 = dt.date(2018, 1, 1)
TW = dt.date(2022, 1, 1)
matches = backtest.load_matches()
lo = T0 - dt.timedelta(days=365 * config.DC_RECENT_YEARS)
pre = [(d, h, a, hs, as_, neu) for d, h, a, hs, as_, t, neu in matches if lo <= d < T0]
base = pois.fit_params(pre, T0)
lam3 = bp.fit_lambda3(base, pre, T0)
dc_out, bp_out, _ = backtest._goals_walk_both(matches, T0, lam3, 1.0, refit_days=45)
try:
    dpar = draw_model.fit(samples=draw_model.collect_samples(upto=T0), persist=False, verbose=False)
    elo_probs = backtest.elo_replay(matches, draw_fn=lambda d, n: draw_model.probs(d, *dpar))
except Exception:
    elo_probs = backtest.elo_replay(matches)

we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
w = we / (we + wd); temp = config.ENSEMBLE_TEMPERATURE
def temper(p):
    if temp == 1.0: return p
    q = [max(p[k], 1e-9) ** (1/temp) for k in range(3)]; s = sum(q); return tuple(x/s for x in q)
def dibp(bpp, f):
    ph, pd, pa = bpp; Z = 1.0 - pd + f * pd
    return (ph/Z, f*pd/Z, pa/Z)

recs = []
for i, m in enumerate(matches):
    if m[0] < T0 or i not in bp_out: continue
    recs.append((m[0], metrics.outcome_index(m[3], m[4]), elo_probs[i], bp_out[i]))
fit = [r for r in recs if r[0] < TW]
ev  = [r for r in recs if r[0] >= TW]

def ens_rps(rows, f):
    s = 0.0
    for d, o, ep, bpp in rows:
        dp = dibp(bpp, f)
        en = temper(tuple(w*ep[k] + (1-w)*dp[k] for k in range(3)))
        s += metrics.rps(en, o)
    return s / len(rows)

factors = [1.0, 1.05, 1.10, 1.15, 1.20, 1.25, 1.30, 1.40, 1.50]
best, bestR = 1.0, 9.9
for f in factors:
    r = ens_rps(fit, f)
    if r < bestR: bestR, best = r, f
print(f"\n  Diagonal-factor RPS tune  (fit n={len(fit)} <{TW}, eval n={len(ev)} >={TW})")
print(f"  {'factor':>8}{'fit RPS':>12}{'eval RPS':>12}")
for f in factors:
    mark = "  <- best on fit" if f == best else ""
    print(f"  {f:>8.2f}{ens_rps(fit, f):>12.5f}{ens_rps(ev, f):>12.5f}{mark}")
print(f"\n  eval RPS: factor 1.00 (no inflation) = {ens_rps(ev,1.0):.5f}   "
      f"best-on-fit {best:.2f} = {ens_rps(ev,best):.5f}   delta {ens_rps(ev,best)-ens_rps(ev,1.0):+.5f}")
