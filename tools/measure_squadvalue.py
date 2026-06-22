"""Strict leakage-free confirmation that squad value adds signal beyond Elo.

Leakage controls:
  * Elo: predict-before-update (online).
  * draw model: fit on matches strictly before the window.
  * value COEFFICIENT (gamma): re-fit each month on ONLY past value-pair matches
    (expanding window) — never sees the match it is scoring. This removes all
    parameter look-ahead.
  * value DATA: a static 2026-06 snapshot. Squad value is slow-moving, so for the
    2025-2026 eval window the snapshot ~= as-of value (negligible look-ahead); for
    the WC2026 matches it is contemporaneous (zero). A fully clean *historical*
    confirmation would need as-of-date values — flagged, not hidden.
"""
from __future__ import annotations
import os, sys, math, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from db import connect
from models import metrics, draw_model
from models.elo import _k_for, _gd_multiplier, expected_score
from sources import squadvalue

WIN = dt.date(2024, 1, 1)
EVAL = dt.date(2025, 7, 1)
GRID = [0, 10, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200]

vt = {t: math.log10(v) for t, v in squadvalue.load().items()}
with connect() as c:
    rows = c.execute(
        """SELECT match_date,home_team,away_team,home_score,away_score,tournament,neutral
           FROM matches WHERE status='finished' AND home_score IS NOT NULL AND away_score IS NOT NULL
           ORDER BY match_date,id""").fetchall()
params = draw_model.fit(samples=draw_model.collect_samples(upto=WIN), persist=False, verbose=False)

elo, recs = {}, []
for d, home, away, hs, as_, tourn, neutral in rows:
    ra, rb = elo.get(home, config.ELO_START), elo.get(away, config.ELO_START)
    ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
    if d >= WIN and home in vt and away in vt:
        recs.append((d, (ra + ha) - rb, vt[home] - vt[away],
                     metrics.outcome_index(hs, as_), "World Cup" in (tourn or "")))
    exp = expected_score(ra + ha, rb); sh = 1.0 if hs > as_ else (0.0 if hs < as_ else 0.5)
    mult = _gd_multiplier(hs - as_) if config.ELO_USE_GD else 1.0
    delta = _k_for(tourn) * config.ELO_K_SCALE * mult * (sh - exp)
    elo[home], elo[away] = ra + delta, rb - delta

def fit_gamma(hist):
    if len(hist) < 50:
        return 0
    best, bestR = 0, 9.9
    for g in GRID:
        r = sum(metrics.rps(draw_model.probs(df + g * vd, *params), o) for df, vd, o in hist) / len(hist)
        if r < bestR: bestR, best = r, g
    return best

hist, gamma, last_m = [], 0, None
ev_base, ev_wf, ev_wf_wc, ev_base_wc, gtrace = [], [], [], [], []
for d, df, vd, o, is_wc in recs:
    if d >= EVAL:
        m = (d.year, d.month)
        if m != last_m:
            gamma = fit_gamma(hist); last_m = m; gtrace.append((d, gamma))
        ev_base.append((draw_model.probs(df, *params), o))
        ev_wf.append((draw_model.probs(df + gamma * vd, *params), o))
        if is_wc:
            ev_base_wc.append((draw_model.probs(df, *params), o))
            ev_wf_wc.append((draw_model.probs(df + gamma * vd, *params), o))
    hist.append((df, vd, o))

def rps(pairs): return metrics.score_stream(pairs)["rps"] if pairs else float("nan")
print(f"\n  STRICT leakage-free walk-forward (gamma re-fit monthly on past only)")
print(f"  eval from {EVAL}, n_eval={len(ev_base)} (of which WC2026={len(ev_wf_wc)})")
print(f"  gamma trajectory: {[(str(d)[:7], g) for d, g in gtrace]}")
print(f"\n  all eval:  Elo-only {rps(ev_base):.5f}   Elo+value(WF) {rps(ev_wf):.5f}   "
      f"delta {rps(ev_wf)-rps(ev_base):+.5f}")
print(f"  WC2026:    Elo-only {rps(ev_base_wc):.5f}   Elo+value(WF) {rps(ev_wf_wc):.5f}   "
      f"delta {rps(ev_wf_wc)-rps(ev_base_wc):+.5f}")
