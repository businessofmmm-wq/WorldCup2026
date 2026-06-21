---
name: backtest-tune
description: >
  Measure and improve the WCPA match model's accuracy. Use when asked to
  "backtest", "tune", "calibrate", "recalibrate", "check model accuracy", or
  "did the model get better". Wraps the leakage-free walk-forward backtest, the
  held-out grid tuner, and the live temperature recalibration into one prescriptive,
  validation-gated workflow. Read-only against the DB except the final --apply step.
---

# Backtest, tune & recalibrate WCPA

The model is only allowed to change if a measured, leakage-free metric improves.
RPS (Ranked Probability Score) is the primary gate — **lower is better**.

## Step 1: Establish the baseline (read-only)
1. `python run.py backtest 2022 --refit 45` — walk-forward RPS / log-loss / Brier
   from 2022 onward. Record the RPS; this is the number to beat.
2. `python run.py backtest 2022 --compare` — bivariate-Poisson vs Dixon-Coles head-to-head.
3. Never tune on the same data you score on. The backtest is walk-forward and
   leakage-free by construction — keep it that way.

## Step 2: Tune held-out parameters
1. `python run.py tune` — grid-tunes on held-out RPS, writes `data/tuned_params.json`.
2. `python run.py calibrate` — fits the ensemble temperature.
3. Re-run Step 1's backtest. **Only keep the new params if RPS dropped.**
   To revert: delete `data/tuned_params.json`.

## Step 3: Live recalibration (in-tournament)
1. `python -m tools.recalibrate` — reports the live-optimal temperature T vs the
   historical-optimal T from frozen pre-kickoff predictions (no leakage; small sample).
2. Review the report. Only if it is a clear improvement:
   `python -m tools.recalibrate --apply` (blends live + historical T before writing).

## Step 4: Validation gate (required)
1. Confirm the post-change backtest RPS <= the baseline from Step 1.
2. `python run.py audit` must stay GREEN.
3. If either regresses, revert (`git checkout -- data/tuned_params.json`) and report why.

## Step 5: Independent review (sub-agent)
Spawn a sub-agent (Task tool) to review the change with fresh eyes. Give it ONLY:
the baseline metrics, the new metrics, and the diff of changed params/config — NOT
the tuning rationale. Ask it to confirm the improvement is real (not noise on a small
sample) and that no leakage was introduced. Incorporate its verdict before committing.
