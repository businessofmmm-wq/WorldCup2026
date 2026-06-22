"""Does squad market value add 1X2 signal BEYOND Elo, out-of-sample?

Elo is replayed predict-before-update. For matches where both teams have a value,
we map (elo_diff + gamma*value_logdiff) through the engine's draw model. gamma (Elo
points per log10-EURm of squad-value difference) is fit on the earlier slice and
evaluated on the later slice. gamma=0 is the Elo-only baseline. Note: values are a
static June-2026 snapshot, so the eval window is kept recent (closest to the snapshot)."""
from __future__ import annotations
import os, sys, math, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from db import connect
from models import metrics, draw_model
from models.elo import _k_for, _gd_multiplier, expected_score
from sources import squadvalue

WIN = dt.date(2024, 1, 1)     # test window start
SPLIT = dt.date(2025, 7, 1)   # fit < SPLIT <= eval (eval = most recent, closest to value snapshot)

vt = {t: math.log10(v) for t, v in squadvalue.load().items()}
with connect() as c:
    rows = c.execute(
        """SELECT match_date, home_team, away_team, home_score, away_score, tournament, neutral
           FROM matches WHERE status='finished' AND home_score IS NOT NULL AND away_score IS NOT NULL
           ORDER BY match_date, id""").fetchall()
params = draw_model.fit(samples=draw_model.collect_samples(upto=WIN), persist=False, verbose=False)

elo, recs = {}, []
for d, home, away, hs, as_, tourn, neutral in rows:
    ra, rb = elo.get(home, config.ELO_START), elo.get(away, config.ELO_START)
    ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
    if d >= WIN and home in vt and away in vt:
        recs.append((d, (ra + ha) - rb, vt[home] - vt[away], metrics.outcome_index(hs, as_)))
    exp = expected_score(ra + ha, rb)
    sh = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
    mult = _gd_multiplier(hs - as_) if config.ELO_USE_GD else 1.0
    k = _k_for(tourn) * config.ELO_K_SCALE * mult
    delta = k * (sh - exp)
    elo[home], elo[away] = ra + delta, rb - delta

fit = [r for r in recs if r[0] < SPLIT]
ev  = [r for r in recs if r[0] >= SPLIT]

def rps_at(rows, g):
    return sum(metrics.rps(draw_model.probs(diff + g * vdiff, *params), o)
               for _, diff, vdiff, o in rows) / len(rows)

grid = [0, 10, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200]
best, bestR = 0, 9.9
for g in grid:
    r = rps_at(fit, g)
    if r < bestR: bestR, best = r, g

print(f"\n  Squad value beyond Elo  (fit n={len(fit)} <{SPLIT}, eval n={len(ev)} >={SPLIT})")
print(f"  best gamma on fit half: {best} Elo-pts per log10-EURm")
print(f"  {'gamma':>6}{'fit RPS':>11}{'eval RPS':>11}")
for g in grid:
    mark = "  <- best on fit" if g == best else ""
    print(f"  {g:>6}{rps_at(fit,g):>11.5f}{rps_at(ev,g):>11.5f}{mark}")
print(f"\n  EVAL: Elo-only (gamma 0) = {rps_at(ev,0):.5f}   "
      f"Elo+value (gamma {best}) = {rps_at(ev,best):.5f}   delta {rps_at(ev,best)-rps_at(ev,0):+.5f}")
