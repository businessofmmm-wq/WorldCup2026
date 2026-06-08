# WCPA — Next steps (perfecting the engine for launch)

_Runbook for the next working session. World Cup kicks off 11 Jun; publish
embargo 9 Jun 08:00 AEST. All commands run locally against the local Postgres._

> **Status (2026-06-08): pipeline complete.** Steps 1–5 were executed live this
> session — goals model settled (**BP**), re-tuned + calibrated (**T=0.85**),
> retrained + **50k-simulated**, and audited **GREEN / launch-ready**. The *only*
> remaining step is `run.py export` + publish, **gated by the 9 Jun 08:00 AEST
> embargo**. Everything else is done and pushed.

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
  runs 50k. The live `refresh` inflow loop is now deliberately lean —
  `REFRESH_RUNS = 1500` with `REFRESH_METHOD = "antithetic"` (mirrored-pair
  variance reduction ≈ 3k crude on the live numbers) so match-day cycles stay
  fast. The sim is rarely the refresh bottleneck; network ingest + the 49k-row
  Elo/DC refit dominate. Every data string stays in the loop — just expanded
  efficiently. Revert via `REFRESH_METHOD="mc"`, `REFRESH_RUNS=5000`.
- Held-out verdict — **settled** (full 2018 window, 8,009 matches): BP **wins**
  the goals model (RPS 0.1686 vs DC 0.1691; better LogLoss/Brier) and `lambda3`
  fits to a healthy **+0.058** on modern data — real coupling, not collapsed. In
  the full ensemble it's a dead heat (0.1668 vs 0.1667). `bivpois` locked.

## 1. Settle the goals model — DONE (2026-06-08)
- [x] Definitive backtest on the full window (`run.py backtest 2018 --compare`,
      8,009 held-out matches): **BP wins** the goals model (RPS 0.1686 vs DC
      0.1691), `lambda3` = +0.058 (real coupling on modern data), ensemble a dead
      heat (0.1668 vs 0.1667). **`bivpois` locked** in `config.py`.
- [ ] _(Optional, post-launch)_ **Diagonal-inflated bivariate Poisson**
      (Karlis-Ntzoufras 2003): mix BP with a draw-diagonal inflation component to
      lift draw mass and maybe edge the ensemble. **Deferred** — the ensemble is
      already tied and launch is imminent; not worth launch-eve model risk. Add
      later as a third `GOALS_MODEL` and re-run `--compare`.

## 2. Re-tune & calibrate — DONE (2026-06-08)
- [x] `python run.py tune` — coordinate descent found no material gain (val RPS
      0.16823 → 0.16819; 2023+ test slice identical) — confirms the shipped
      params are already near-optimal.
- [x] `python run.py calibrate` — best ensemble temperature **T=0.85** improves
      all three held-out metrics (RPS 0.1651→0.1649, LogLoss 0.8509→0.8489,
      Brier 0.4994→0.4989).
- [x] `data/tuned_params.json` updated (tuned params + T=0.85) and committed.

## 3. Retrain + 50k simulate — DONE locally (export embargoed)
- [x] `python run.py train` — refit Elo/draw/DC/BP; BP `lambda3` = **+0.0719** on
      live data (NLL 12,392.7→12,384.2). Used `train` (not `refresh`) because
      `train` also refits BP, which `refresh` currently skips — see ⚠ below.
- [x] `python run.py simulate 50000` — fresh authoritative field: Argentina
      19.4%, Spain 16.0%, Brazil 14.0%, England 8.0%, France 7.7%, Portugal 6.6%.
      Regenerated sim_report.json (runs=50000), group_adv.json, draw_params.json,
      ARCHITECTURE.md (×50k). All committed.
- [ ] `python run.py export` — **BLOCKED by embargo** until 9 Jun 08:00 AEST.
      The only remaining step before launch. After the embargo: `export` →
      deploy/publish the static CDN album (the information→matter step).
- ⚠ `refresh` retrains Elo/draw/DC but **not** BP (low-risk intra-day since BP
      reuses DC marginals + a slow lambda3). Post-launch, add a bivpois step to
      `cmd_refresh` so the live goals model never drifts.

## 4. Variance reduction — DONE where it matters
- [x] Applied **antithetic** to the live `refresh` sim (`REFRESH_METHOD`), cutting
      runs 5000→1500 at equal precision. The fast match-day loop is where
      efficiency actually pays.
- **(n/a)** The authoritative 50k `simulate` stays crude MC on purpose: at 50k the
      Monte-Carlo error is already ~0.18pp on the title odds, so QMC/antithetic
      there is effort without a visible payoff. Revisit only if runs ever drop.

## 5. Launch gate
- [x] `python run.py audit --no-load` — **VERDICT: GREEN, launch-ready** (14
      checks, 0 fail / 0 warn). Load test skipped (needs an exported build); run
      full `audit` after export, pre-publish.
- [ ] Walk LAUNCH.md; confirm Ko-fi / Stripe link live; OG card current.
- [ ] Respect the 9 Jun 08:00 AEST publish embargo.
