# WCPA26 — Model Accuracy: Research & Method-Upgrade Plan

**Date:** 2026-06-21
**Current held-out scores** (walk-forward, leakage-free, 8,009 internationals 2018+):

| Metric | Now | Base rate | Read |
|---|---|---|---|
| RPS | **0.1667** | 0.2267 | ~26% better than base rate — good |
| Log-loss | 0.8565 | — | competitive |
| Brier (3-class) | 0.5037 | — | competitive |
| Calibration (ECE) | **0.0112** | — | near-optimal; little left here |

## The key insight: you're calibrated, so chase *sharpness*

ECE of 0.011 means your probabilities are already honest — when you say 30%, it happens
~30% of the time. The forecasting literature is explicit that once a model is calibrated,
further gains must come from **resolution/sharpness** (a stronger underlying team-strength
signal), not more calibration — the modern paradigm is "maximise sharpness *subject to*
calibration" ([arXiv 1112.6390](https://arxiv.org/pdf/1112.6390),
[arXiv 2106.14345](https://arxiv.org/pdf/2106.14345)). So the temperature/calibration layer
is basically done; the work is upstream, in the ratings and goal model.

**A caveat on the number itself.** RPS 0.167 is *not* comparable to the ~0.206 you'll see
quoted for EPL models (e.g. pi-ratings + XGBoost 0.2063, Hybrid Bayesian Net 0.2083 —
[Constantinou/Fenton lineage](https://www.eecs.qmul.ac.uk/~norman/papers/evaluating_predictive_accuracy_football.pdf)).
International football has far more mismatches (Brazil v San Marino) than a league, which
mechanically lowers RPS. Don't celebrate or panic on the cross-domain gap — your own
base-rate delta (−26%) and walk-forward deltas are the honest yardstick.

---

## Prioritised upgrades (each fits the pure-Python / tiny-deps ethos unless flagged)

| # | Upgrade | Lever | Effort | Expected RPS impact | Ethos fit |
|---|---------|-------|--------|---------------------|-----------|
| 1 | xG-based team strength | resolution | Med | **Largest available** | ✅ data already ingested |
| 2 | pi-ratings as 2nd rating | resolution | Med | Medium | ✅ pure recursion |
| 3 | Diagonal-inflated bivariate Poisson | draw calibration | Low–Med | Small (draws) | ✅ already a TODO |
| 4 | Tune time-decay ξ | resolution | Low | Small | ✅ uses `tune` |
| 5 | Market-odds anchor/feature | resolution | Med | High | ⚠️ trade-offs |
| 6 | Squad availability (injuries/lineups) | resolution | Med–High | Small–Med, noisy | ✅ API-Football |
| 7 | Stacked ensemble weights | resolution | Med | Small–Med | ✅ arithmetic |
| 8 | Bivariate Weibull count model | goal model | High | Med (research) | ⚠️ heavier |

### 1 — Use xG as the strength signal (biggest in-house lever)
You already ingest StatsBomb and balldontlie xG (`sources/statsbomb.py`,
`sources/balldontlie.py`) but only for *past* World Cups. xG is more stable and more
predictive of future results than actual goals because it strips finishing variance — a
team that created 2.1 xG but scored 0 is usually unlucky, not bad. Build an **xG-adjusted
attack/defence rating** (or blend xG- and goal-based Dixon-Coles marginals) so the engine
learns from chances created, not just the scoreline. The xG→outcome link is well documented
([PMC10075453](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC10075453/),
[PLOS One](https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0312278)).
*Catch:* xG coverage for international football is thinner than club; design it as a
blended signal that gracefully falls back to goals when xG is missing (you already have the
graceful-degradation convention).

### 2 — Add pi-ratings alongside Elo
Constantinou & Fenton's pi-ratings rate teams on the *margin* of score discrepancies, keep
**separate home/away ratings**, and weight recent form — and were shown to beat Elo and to
be profitable against bookmaker odds over five EPL seasons
([penaltyblog summary](https://pena.lt/y/2025/04/14/pi-ratings-the-smarter-way-to-rank-football-teams/),
[Constantinou 2012](https://www.eecs.qmul.ac.uk/~norman/papers/evaluating_predictive_accuracy_football.pdf)).
It's a short pure-Python recursion. Add `models/pirating.py`, expose a 1X2 from it, and
fold it into the ensemble next to Elo and Dixon-Coles. This is the highest-ROI *new model*
because it captures information Elo throws away (margin + venue split).

### 3 — Diagonal-inflated bivariate Poisson (already on your list)
Karlis & Ntzoufras (2003) add a diagonal-inflation term so draw scorelines are better
calibrated than plain/independent Poisson; a study reports Brier dropping with draw
inflation + period weighting ([Grokipedia: Dixon–Coles](https://grokipedia.com/page/DixonColes_model)).
Your `NEXTSTEPS.md` already flags "diagonal-inflated bivariate-Poisson as a 3rd GOALS_MODEL"
— this validates it. Extend `models/bivpoisson.py` with the inflation parameter and let
`tune` fit it. Gains are concentrated on draw-likely matches, so modest overall but cheap.

### 4 — Re-tune the time-decay half-life
Dixon-Coles down-weights old matches; the literature puts the optimal daily decay around
ξ ≈ 0.00325 over multi-season data ([Grokipedia](https://grokipedia.com/page/DixonColes_model),
[dashee87](https://dashee87.github.io/football/python/predicting-football-results-with-statistical-modelling-dixon-coles-and-time-weighting/)).
You already grid-tune on held-out RPS — add the decay constant (and separate attack vs
defence decay) to the sweep. Quick, low-risk, occasionally a real win.

### 5 — Market odds as a feature/anchor (high impact, real trade-offs)
Devigged bookmaker (closing) odds are the strongest single baseline in the field and are
hard to beat ([diva2:1772002](https://hj.diva-portal.org/smash/get/diva2:1772002/FULLTEXT01.pdf),
[ScienceDirect S0169207014000533](https://www.sciencedirect.com/science/article/abs/pii/S0169207014000533)).
Two honest options, with trade-offs:
- **As a benchmark only:** ingest historical closing odds (football-data.co.uk is free) and
  add "vs market RPS" to the backtest. This tells you how close you are to the ceiling
  without changing the model. Low risk, pure measurement.
- **As a blended feature:** mix devigged market probabilities into the ensemble. Biggest
  accuracy jump — but you're then partly *tracking* the market rather than beating it, and
  it imports the very betting-data your site deliberately stays clear of (AU IGA stance in
  `app.js`). Using odds as input data is not promoting gambling, but flag the optics. I'd
  start with the benchmark, decide on blending after seeing the gap.

### 6 — Squad availability
You have API-Football lineups/injuries (`sources/apifootball.py`). A star striker out
materially shifts a team's attack. Feature engineering and domain signal are repeatedly
called the decisive factor in this low-scoring sport
([ResearchGate 352846677](https://www.researchgate.net/publication/352846677)). But it's
noisy and labour-intensive to do cleanly; treat as a later, opt-in refinement.

### 7 — Stack the ensemble properly
Today you blend Elo-1X2 (ordered-logit draw model) + Dixon-Coles-1X2 under one temperature.
With pi-ratings and an xG-DC variant added, optimise the **blend weights** on held-out data
(simple logistic stack), rather than a fixed mix. Better combination of the same signals is
a free resolution gain.

### 8 — (Research) Bivariate Weibull count model
Boshnakov/Kharrat/McHale's Weibull count model relaxes the Poisson mean=variance assumption
and outperforms Poisson families on score forecasting
([ScienceDirect S0169207017300018](https://www.sciencedirect.com/science/article/abs/pii/S0169207017300018)).
It's a bigger, heavier rewrite (numerically fiddly MLE) and brushes against the
tiny-deps rule — park it as a future direction, not a sprint item.

---

## Measurement discipline (do this *first* — it protects every change above)
With 8,009 matches, the RPS improvements on offer are small (think 0.166 → ~0.160). At that
scale you can easily chase noise. Before tuning:
1. Keep the walk-forward, leakage-free protocol exactly as is (it's your biggest asset).
2. Add a **significance test** on RPS deltas — paired bootstrap or Diebold-Mariano over the
   per-match scores — so "RPS dropped 0.0008" is only accepted if it's real, not variance.
   Your `/backtest-tune` skill already gates on RPS; this makes the gate trustworthy.
3. Report RPS **and** log-loss/Brier together; RPS has known biases as a sole metric
   ([arXiv 1908.08980, "the case against RPS"](https://arxiv.org/pdf/1908.08980)).

## Suggested roadmap
- **Phase 0 (now):** add the significance test + market-odds *benchmark* (measurement only).
- **Phase 1:** re-tune time-decay (#4) and ship diagonal-inflated BP (#3) — cheap, your list.
- **Phase 2:** xG-adjusted strength (#1) and pi-ratings (#2) — the real resolution gains.
- **Phase 3:** stacked ensemble weights (#7); decide on market blending (#5) on the evidence.
- **Later:** squad availability (#6), Weibull model (#8) as research.

## Honest ceiling
Football is irreducibly random; bookmakers sit near the practical limit and are rarely beaten
net. Realistically these levers move internationals RPS from ~0.167 toward ~0.158–0.162 with
diminishing returns — a genuine, defensible improvement, not a step change. The xG signal
(#1) and pi-ratings (#2) are where I'd put the effort first.

I can implement any single lever end-to-end against your backtest (I'd start with the
significance test + pi-ratings, since they're self-contained and measurable). Say which.

---
_Sources are linked inline. Searches run 2026-06-21; figures quoted are from the cited
papers/posts and are league-football unless noted — treat them as directional, not as
targets for your internationals dataset._
