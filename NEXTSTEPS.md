# WCPA — Next steps (perfecting the engine for launch)

_Runbook for the next working session. World Cup kicks off 11 Jun; publish
embargo 9 Jun 08:00 AEST. All commands run locally against the local Postgres._

## State at hand-off (2026-06-08)
- Three commits landed on `wcpa-launch-prep`: variance-reduction benchmark,
  refreshed 20k sim snapshot, and the **bivariate-Poisson goals model**.
- Goals model is **pluggable** (`config.GOALS_MODEL`): `dixon_coles` (live
  default) | `bivpois`. Both share the time-decayed attack/defence MLE.
- Held-out verdict so far (2022 window): **tie** — DC a hair better in the
  ensemble (RPS 0.1685 vs 0.1688). BP's `lambda3` collapses to ~0 on pre-test
  data because it can't represent football's slight *negative* goal dependence.

## 1. Settle the goals model (the open question)
- [ ] Definitive backtest on the full window: `python run.py backtest 2018 --compare`
      (more held-out matches → tighter RPS gap than the 2022 quick run).
- [ ] Try the **diagonal-inflated bivariate Poisson** (Karlis-Ntzoufras 2003):
      mix the BP with an inflation component on the draw diagonal. Unlike plain
      BP this *can* lift draw mass to match data and may finally beat DC's tau.
      Add as a third `GOALS_MODEL` option; re-run `--compare`.
- [ ] Lock the default to whichever wins; note it in `config.py`.

## 2. Re-tune & calibrate to the chosen model
- [ ] `python run.py tune`       (coordinate-descent on held-out RPS)
- [ ] `python run.py calibrate`  (fit the ensemble temperature)
- [ ] Confirm `data/tuned_params.json` reflects the winner.

## 3. Retrain on latest data + refresh the live album
- [ ] `python run.py refresh`    (live+news inflow → retrain → resim)
- [ ] `python run.py simulate`   (fresh 20k title odds)
- [ ] `python run.py export`     (rebuild the static CDN snapshot)

## 4. Optional: bank the variance-reduction win on the live sim
- [ ] Decide whether to switch the live `simulate` from crude MC to antithetic/
      QMC (see VARIANCE.md). Control-variate gives ~4x on group advancement.

## 5. Launch gate
- [ ] `python run.py audit`  must pass (security + stability + load + hygiene).
- [ ] Walk LAUNCH.md; confirm Ko-fi / Stripe link live; OG card current.
- [ ] Respect the 9 Jun 08:00 AEST publish embargo.
