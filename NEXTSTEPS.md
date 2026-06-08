# WCPA — Next steps (perfecting the engine for launch)

_Runbook for the next working session. World Cup kicks off 11 Jun; publish
embargo 9 Jun 08:00 AEST. All commands run locally against the local Postgres._

## The lens — a quantum view of the tournament
_Samuel's framing, and it's faithful to what the engine actually is — keep
building through it. A frame, not a fudge: the verdicts below stay measured._

- **Every possibility, held in superposition.** The Monte-Carlo sim holds the
  whole tournament as a superposition of futures; each of the **50,000** runs is
  one sampled, collapsed world. The bivariate-Poisson scoreline grid is the
  amplitude distribution over *every* possible scoreline — the shared term
  `lambda3` is the coupling (the "entanglement") between home and away goals,
  the part independent Poissons miss.
- **Every string of knowledge, woven in.** Results, live scores, news, xG — each
  an information string folded into one state. The lens says: don't drop a
  string, and keep adding strings (availability, injuries) as they become free.
- **Expand it quantumly, efficiently.** More sampled worlds = the possibility
  space resolved more finely. Variance reduction (`models/variance.py` —
  QMC / antithetic / control-variate) is how we expand to 50k without paying 50k
  of cost; it's the efficient basis for the same superposition.
- **Information → matter.** The export step is where abstract probability becomes
  a *tangible* artifact — the static album on the CDN, the OG card, ultimately a
  printable physical Prediction Album. That's the through-line: take the full
  field of possibility and make it something you can hold.

## State at hand-off (2026-06-08)
- On `wcpa-launch-prep`: variance-reduction benchmark, refreshed sim snapshot,
  the **bivariate-Poisson goals model** (now the live default), and the
  **50k sim** bump across config/scripts/docs/site.
- Goals model is **pluggable** (`config.GOALS_MODEL`): `bivpois` (live) |
  `dixon_coles`. Both share the time-decayed attack/defence MLE.
- `SIM_RUNS = 50000`. The authoritative odds path (`simulate` / `deploy.bat`)
  runs 50k. The live `refresh` inflow loop stays at 5k on purpose — it fires
  every 30 min on match days and must stay fast; bump it only if a cycle's lag
  is acceptable.
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
- [ ] `python run.py refresh`         (live+news inflow → retrain → resim)
- [ ] `python run.py simulate 50000`  (fresh 50k title odds — the full field)
- [ ] `python run.py export`          (rebuild the static CDN snapshot — the
      information→matter step; regenerates sim_report.json / FINDINGS.md /
      ARCHITECTURE.md at the new 50k count).

## 4. Optional: bank the variance-reduction win on the live sim
- [ ] At 50k the efficiency matters more — decide whether to switch the live
      `simulate` from crude MC to antithetic/QMC (see VARIANCE.md). Control-
      variate gives ~4x on group advancement; that's the lever that makes the
      bigger superposition affordable.

## 5. Launch gate
- [ ] `python run.py audit`  must pass (security + stability + load + hygiene).
- [ ] Walk LAUNCH.md; confirm Ko-fi / Stripe link live; OG card current.
- [ ] Respect the 9 Jun 08:00 AEST publish embargo.
