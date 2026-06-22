"""Find the pi blend weight that is optimal against the ENGINE'S production-faithful
ensemble (DC re-anchored at the test start), leakage-free: fit weight on the earlier
half of the test window, evaluate on the later half."""
from __future__ import annotations
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from models import backtest, metrics, pirating, draw_model

T0 = dt.date(2022, 1, 1)
matches = backtest.load_matches()
try:
    dp = draw_model.fit(samples=draw_model.collect_samples(upto=T0), persist=False, verbose=False)
    elo_probs = backtest.elo_replay(matches, draw_fn=lambda d, n: draw_model.probs(d, *dp))
except Exception:
    elo_probs = backtest.elo_replay(matches)
dc_probs = backtest.dc_walkforward(matches, T0, refit_days=45)

pr = pirating.PiRatings(); pi_gd = []
for m in matches:
    pi_gd.append(pr.expected_gd(m[1], m[2], bool(m[6]))); pr.update(m[1], m[2], m[3], m[4], neutral=bool(m[6]))

we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
w = we/(we+wd); temp = config.ENSEMBLE_TEMPERATURE
def temper(p):
    if temp == 1.0: return p
    q=[max(p[k],1e-9)**(1/temp) for k in range(3)]; s=sum(q); return tuple(x/s for x in q)
def t(p): return (p["p_home"], p["p_draw"], p["p_away"])

recs=[]
for i,m in enumerate(matches):
    if m[0] < T0 or i not in dc_probs: continue
    o=metrics.outcome_index(m[3],m[4])
    base_pre=tuple(w*elo_probs[i][k]+(1-w)*dc_probs[i][k] for k in range(3))
    pi=t(pirating.gd_to_1x2(pi_gd[i]))
    recs.append((m[0],base_pre,pi,o))
recs.sort(key=lambda r:r[0])
mid=len(recs)//2
fit, test = recs[:mid], recs[mid:]
def mix(b,p,wp):
    q=[(1-wp)*b[k]+wp*p[k] for k in range(3)]; s=sum(q); return tuple(x/s for x in q)
def rps_of(rows,wp):
    return sum(metrics.rps(temper(mix(b,p,wp)),o) for _,b,p,o in rows)/len(rows)

best,bestR=0.0,9.9
for wp in [x/100 for x in range(0,55,5)]:
    r=rps_of(fit,wp)
    if r<bestR: bestR,best=r,wp
print(f"\n  pi weight sweep vs production base (fit n={len(fit)}, eval n={len(test)})")
print(f"  optimal weight on fit half: {best:.2f}")
print(f"  eval-half RPS:  wp=0.00 -> {rps_of(test,0.0):.4f}   wp={best:.2f} -> {rps_of(test,best):.4f}   wp=0.40 -> {rps_of(test,0.40):.4f}")
