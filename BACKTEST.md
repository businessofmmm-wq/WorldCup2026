# World Cup 2026 — Backtest & Accuracy

*How accurate is the match model, and how do we know? This file is the
measurement layer: a leakage-free walk-forward over real history, scored with
the standard probabilistic-forecast metrics. Every model change in the engine
was accepted only if it improved these held-out numbers. Reproduce with
`python run.py backtest`.*

---

## 1. Why this exists

The engine produced predictions but never scored them, so "accurate" was
unfalsifiable. `models/backtest.py` fixes that: for every finished international
in a held-out window it reconstructs the prediction the engine *would* have made
knowing only what happened **before** that match, then scores it. That number is
the objective the rest of the work optimises.

## 2. Methodology (leakage-free)

- **Elo** is replayed chronologically; each match is predicted from the ratings
  as they stand *before* it is folded in (predict-before-update). Honest in one
  pass.
- **Dixon-Coles** is a batch fit, so it is refit on a walk-forward: every
  `refit_days` a new fit is made (`poisson.fit_params`) anchored at its as-of
  date, seeing only prior matches, with the time-decay clock reset to that date.
  Refits warm-start from the previous one for speed.
- **Ensemble** blends the two aligned 1X2 vectors and applies the calibration
  temperature — exactly the production path.
- **Metrics.** Ranked Probability Score (**RPS**, the standard ordered-outcome
  football metric — lower is better), log-loss, multiclass Brier, argmax
  accuracy, and a reliability/calibration error (**ECE**, mean |predicted −
  observed| across the three classes). Two naive baselines (uniform, and the
  pre-test home/draw/away base rate) bound how much signal the models add.
- **No overfitting the metric.** Hyperparameters were grid-searched on a
  **validation** slice (2018–2022) and the result reported once on an untouched
  **test** slice (2023→present). See `models/tune.py`.

## 3. Results

Test window = every finished men's international from the date shown
(`N` matches). Lower RPS / LogLoss / Brier / ECE = better; higher Acc = better.

### Naive baselines (full window, 2018+, N=8009)
| Model | RPS | LogLoss | Brier | Acc |
|---|---|---|---|---|
| Uniform (1/3 each) | 0.2394 | 1.0986 | 0.6667 | 0.477 |
| Base rate (H/D/A split) | 0.2267 | 1.0472 | 0.6308 | 0.477 |

### Engine — baseline vs tuned/calibrated
| Window | Model | RPS | LogLoss | Brier | Acc | ECE |
|---|---|---|---|---|---|---|
| **Full 2018+** (N=8009) | baseline | 0.1680 | 0.8634 | 0.5069 | 0.607 | 0.0228 |
| | **final** | **0.1667** | **0.8565** | **0.5037** | 0.604 | **0.0112** |
| **Held-out 2023+** (N=3500) | baseline | 0.1655 | 0.8541 | 0.5011 | 0.608 | 0.0245 |
| | **final** | **0.1650** | **0.8492** | **0.4991** | 0.602 | **0.0191** |

The model beats the base-rate baseline by ~26% RPS — most of the value is in the
models themselves. On top of that, tuning + the new draw model + calibration buy
a further, fully held-out improvement on every probabilistic metric, with the
clearest gain in **calibration** (full-window ECE roughly halved, 0.0228 →
0.0112: the stated probabilities now track observed frequencies almost exactly).
Argmax accuracy dips ~0.4pt — expected, since RPS/log-loss (not hit-rate) are the
right objectives for a probabilistic forecaster.

## 4. What changed (all held-out-validated)

| Parameter | Before | After | Why |
|---|---|---|---|
| Dixon-Coles half-life | 600 d | **1300 d** | Nations play ~10×/yr; recency was over-weighted |
| Dixon-Coles L2 (`reg`) | 0.08 | **0.04** | Less shrinkage helped out-of-sample |
| Dixon-Coles `rho` | −0.11 | **−0.15** | Slightly stronger low-score correction |
| Elo K-scale | 1.0 | **0.85** | Calmer ratings predict better |
| Elo home advantage | 65 | **110** | Empirically larger home edge |
| Ensemble blend (Elo:DC) | 0.45:0.55 | **0.40:0.60** | DC carries marginally more |
| Elo → 1X2 draw model | linear shrink | **ordered logit** | Learned from data, not assumed |
| Ensemble temperature | — | **0.85** | Final calibration (sharpening) |

Tuned values live in `data/tuned_params.json` (loaded by `config.py`; delete the
file to revert). The ordered-logit draw model is `models/draw_model.py`
(`data/draw_params.json`).

## 5. Reproduce

```powershell
python run.py backtest 2018      # full metrics table vs baselines
python run.py tune               # re-derive tuned_params.json on held-out RPS
python run.py calibrate          # re-fit the ensemble temperature
```

*Metrics: RPS (Epstein 1969; Constantinou & Fenton 2012), log-loss, multiclass
Brier, reliability/ECE. Walk-forward refit cadence 45 days; validation 2018–2022,
test 2023→present.*
