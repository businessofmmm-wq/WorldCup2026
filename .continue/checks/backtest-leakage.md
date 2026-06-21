---
name: Backtest Leakage & Accuracy
description: Model changes must be measured leakage-free
---
If this PR touches `models/` (elo, poisson, bivpoisson, draw_model, predict, tournament,
tune, variance) or tuning params, confirm: (1) the change is scored on HELD-OUT data via
the walk-forward backtest, not the training set; (2) no future information leaks into a
past prediction; (3) the PR states the before/after RPS and RPS did not regress (lower is
better). FAIL if accuracy is unmeasured or leakage is plausible. Only consider files
changed in this PR.
