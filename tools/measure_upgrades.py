"""
Honest, leakage-free measurement of the calibration upgrades on real held-out
predictions. Uses the engine's own walk-forward backtest stream, then recalibrates
on a TEMPORAL split: fit each recalibrator on the earlier slice of held-out
predictions, apply to the later slice, and compare scores. Recalibration params
therefore come only from the past — no leakage.
"""
from __future__ import annotations
import os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models import backtest, metrics, calibrate

res = backtest.report(dt.date(2018, 1, 1))
ens = res["streams"]["ensemble"]                       # (date, neutral, probs, outcome)
cut = dt.date(2023, 1, 1)
fit_rows  = [(p, o) for d, neu, p, o in ens if d <  cut]
test_rows = [(p, o) for d, neu, p, o in ens if d >= cut]

def scores(rows):
    s = metrics.score_stream(rows)
    return s["rps"], s["brier"], s["log_loss"], metrics.reliability_error(rows)

# fit on the EARLIER slice only
T   = calibrate.fit_vector_temperature(fit_rows)
pri = calibrate.base_rate(fit_rows)
lam = calibrate.fit_shrinkage(fit_rows, pri)

variants = {
    "baseline (current)":      test_rows,
    "+ vector temperature":    [(calibrate.apply_vector_temperature(p, T), o) for p, o in test_rows],
    "+ shrinkage-to-prior":    [(calibrate.apply_shrinkage(p, lam, pri), o) for p, o in test_rows],
    "+ both":                  [(calibrate.apply_shrinkage(calibrate.apply_vector_temperature(p, T), lam, pri), o) for p, o in test_rows],
}

print(f"\n  Leakage-free recalibration on held-out predictions "
      f"(fit <{cut}, test >={cut}, n_test={len(test_rows)})")
print(f"  fitted: T={tuple(round(t,2) for t in T)}  lambda={lam:.2f}  prior={tuple(round(x,2) for x in pri)}\n")
print(f"  {'variant':<24}{'RPS':>9}{'Brier':>9}{'LogLoss':>10}{'ECE':>9}")
print("  " + "-" * 60)
base = None
for name, rows in variants.items():
    rps, br, ll, ece = scores(rows)
    if base is None:
        base = (rps, br, ll, ece)
        tag = ""
    else:
        tag = f"   RPS {rps-base[0]:+.4f}  ECE {ece-base[3]:+.4f}"
    print(f"  {name:<24}{rps:>9.4f}{br:>9.4f}{ll:>10.4f}{ece:>9.4f}{tag}")
