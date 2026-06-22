"""
Rigorous, leakage-free evaluation of pi-ratings in the ensemble.

Splits, all temporal (no leakage):
  * gd->1X2 mapping params  fit on matches BEFORE 2018
  * pi ensemble blend weight fit on 2018..2022
  * everything reported on the 2022+ held-out window
Elo is predict-before-update; DC is the engine's walk-forward; pi-ratings are
replayed online (expected_gd read BEFORE each result is folded in).
"""
from __future__ import annotations
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from models import backtest, metrics, pirating, draw_model

T0 = dt.date(2018, 1, 1)      # DC walk-forward start (and mapping cutoff)
TW = dt.date(2022, 1, 1)      # weight-fit / eval split

matches = backtest.load_matches()

# --- Elo (production-faithful, leakage-free) ---
try:
    dp = draw_model.fit(samples=draw_model.collect_samples(upto=T0), persist=False, verbose=False)
    elo_probs = backtest.elo_replay(matches, draw_fn=lambda d, n: draw_model.probs(d, *dp))
except Exception:
    elo_probs = backtest.elo_replay(matches)

# --- Dixon-Coles walk-forward over 2018+ ---
dc_probs = backtest.dc_walkforward(matches, T0, refit_days=45)

# --- pi-ratings online replay (predict-before-update) over ALL matches ---
pr = pirating.PiRatings()
pi_gd = []
for (d, home, away, hs, as_, tourn, neutral) in matches:
    pi_gd.append(pr.expected_gd(home, away, bool(neutral)))
    pr.update(home, away, hs, as_, neutral=bool(neutral))

def t(p): return (p["p_home"], p["p_draw"], p["p_away"])

# --- fit gd->1X2 mapping on PRE-2018 (gd, outcome) ---
pre_map = [(pi_gd[i], metrics.outcome_index(m[3], m[4]))
           for i, m in enumerate(matches) if m[0] < T0]
best, bestL = (0.8, 1.1), 1e9
for dw in [x/10 for x in range(2, 15)]:
    for sc in [x/10 for x in range(6, 18)]:
        s = n = 0.0
        for gd, o in pre_map:
            s += metrics.log_loss(t(pirating.gd_to_1x2(gd, dw, sc)), o); n += 1
        if s/n < bestL: bestL, best = s/n, (dw, sc)
DW, SC = best

# --- assemble aligned test records (2018+) ---
we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
w = we/(we+wd); temp = config.ENSEMBLE_TEMPERATURE
def temper(p):
    if temp == 1.0: return p
    q = [max(p[k], 1e-9)**(1/temp) for k in range(3)]; s = sum(q); return tuple(x/s for x in q)
def mix(a, b, wp):
    q = [(1-wp)*a[k] + wp*b[k] for k in range(3)]; s = sum(q); return tuple(x/s for x in q)

recs = []  # (date, base_ensemble, pi_1x2, outcome)
for i, m in enumerate(matches):
    d = m[0]
    if d < T0 or i not in dc_probs: continue
    o = metrics.outcome_index(m[3], m[4])
    base = temper(tuple(w*elo_probs[i][k] + (1-w)*dc_probs[i][k] for k in range(3)))
    pi = t(pirating.gd_to_1x2(pi_gd[i], DW, SC))
    recs.append((d, base, pi, o))

fit = [r for r in recs if r[0] < TW]
test = [r for r in recs if r[0] >= TW]

# --- fit pi blend weight on 2018..2022 (minimise RPS) ---
bestw, bestR = 0.0, 1e9
for wp in [x/100 for x in range(0, 61, 5)]:
    s = sum(metrics.rps(mix(b, p, wp), o) for _, b, p, o in fit)/len(fit)
    if s < bestR: bestR, bestw = s, wp

def score(rows, fn):
    pairs = [(fn(r), r[3]) for r in rows]
    s = metrics.score_stream(pairs)
    return s["rps"], s["brier"], s["log_loss"], metrics.reliability_error(pairs)

print(f"\n  Pi-ratings rigorous eval  (map fit <{T0}, weight fit {T0}..{TW}, "
      f"eval >={TW}, n_test={len(test)})")
print(f"  fitted: gd->1X2 draw_width={DW:.1f} scale={SC:.1f} | pi blend weight={bestw:.2f}\n")
print(f"  {'model':<26}{'RPS':>9}{'Brier':>9}{'LogLoss':>10}{'ECE':>9}")
print("  " + "-"*62)
rows = [
    ("pi-ratings (standalone)", lambda r: r[2]),
    ("base ensemble (Elo+DC)",  lambda r: r[1]),
    ("ensemble + pi",           lambda r: mix(r[1], r[2], bestw)),
]
base_rps = None
for name, fn in rows:
    rps, br, ll, ece = score(test, fn)
    tag = ""
    if name == "base ensemble (Elo+DC)": base_rps = rps
    if name == "ensemble + pi" and base_rps is not None:
        tag = f"   RPS {rps-base_rps:+.5f}"
    print(f"  {name:<26}{rps:>9.4f}{br:>9.4f}{ll:>10.4f}{ece:>9.4f}{tag}")
