# Scope — Data Feeds & Club↔International Signal Transfer

**Date:** 2026-06-22 · **For:** WCPA26 · **Status:** scoping only, no code yet

## 0. The governing principle (read this first)
Club football and international football are **different populations** — you must never
pool match *results* across them (a 4-0 in the Bundesliga is not evidence about Brazil).
The only honest bridge is the **player**: a national team is the ~23 players it picks, and
those players mostly generate rich, abundant data in club competition. So the data splits
by *what it can tell you*:

- **Club data → estimates PLAYER quality** (xG/90, minutes, market value, form). Abundant.
- **International data → estimates TEAM-level effects** (cohesion, manager, tournament
  context). Thin, but the *only* source of these — and they are real: a WC squad trains
  ~25 days/year and the starting XI has often never played together
  ([Wangari](https://newsletter.wangari.global/p/stop-trusting-ml-predictions-for)).

Combine **only at the player level**, keep team-level effects separate, and weight club
signal by relevance. This is the academically-validated route — player-rating models that
"relate matches through players and club outcomes" rather than team ratings alone
([Hvattum & Arntzen 2021](https://journals.sagepub.com/doi/10.1177/1471082X20929881);
[player-rating forecasting, 2024](https://ideas.repec.org/a/eee/intfor/v40y2024i1p302-312.html)),
and they keep accuracy across transfer windows because the unit is the player, not the team.

---

## 1. Which factors actually transfer (the significance map)
The thing you asked for — only scrape what's cross-relevant, and keep the significances
separate:

| Factor | Club → International? | Why | Source (free unless noted) |
|---|---|---|---|
| Player xG/xA per 90 | **Yes (via player)** | finishing/creation skill is intrinsic | Understat, FBref, API-Football(paid) |
| Player minutes / load / fitness | **Yes** | fatigue & sharpness carry over | API-Football, FBref |
| Injuries / availability | **Yes (strong)** | a missing star is a missing star anywhere | API-Football (you have it) |
| Squad market value | **Yes (strong, cheap)** | best-cited single WC proxy for talent | Transfermarkt (scrape) |
| Age / form trajectory | **Yes** | intrinsic to the player | FBref/Transfermarkt |
| League-strength of club | **Normalize, don't transfer raw** | a goal in Ligue 1 ≠ MLS | UEFA/Elo league coeffs |
| Opponent-adjusted output | **Partially** | context-dependent | derived |
| Team cohesion / chemistry | **No** | only exists at national level | international results only |
| Manager / system / set-piece routines | **No** | team-specific | international results only |
| Tournament pressure / knockout dynamics | **No** | xG models don't model "parking the bus" in ET | international results only |
| Travel / altitude / climate (WC2026 hosts) | **No (intl-only)** | venue-specific | fixture metadata |

Rule of thumb: **player attributes transfer; team attributes don't.** The scrape targets the
top block; the bottom block stays the exclusive job of your existing Elo/DC on international
results.

---

## 2. Three data tracks, scoped separately

### Track A — Odds feed
- **Free (club only):** [football-data.co.uk](https://www.football-data.co.uk/data.php) —
  CSV, 25+ domestic leagues, 2000/01→2025/26, 9+ books, pre-match **and closing** odds,
  Pinnacle/Bet365. **$0.** But **no international odds.**
- **International odds (paid):** API-Football odds add-on (**+$10/mo**, your account), or
  [The Odds API](https://the-odds-api.com) (free ~500 req/mo), or OddsPortal scrape (ToS risk).
- **Honest value:** devigged closing odds are the single strongest predictor in the
  literature — but blending them means partly *tracking* the market, and it imports betting
  data your site deliberately avoids (AU IGA). **Best first use: a benchmark** ("how close is
  the model to the market?") in the backtest, not a feature.
- **Effort:** club CSV ingest = **low**; international odds = **medium** + an optics decision.

### Track B — xG / player-stats feed (the real headroom)
- **Free club xG:** [Understat](https://understat.com) (top-5 + RPL, ~2014+, scrapeable),
  FBref/StatsBomb (broad, scrape, ToS-sensitive).
- **Free international xG:** StatsBomb open = WC2018/2022 + some Euros only — **the wall you
  already hit (64 matches in your DB).**
- **Paid, cleanest:** **API-Football player statistics** ($19/mo, all endpoints) — per-player
  per-season club stats (goals, assists, minutes, xG where covered) **and** internationals,
  one source, you already have the client (`sources/apifootball.py`).
- **Honest value:** this is the one lever that adds **new signal** (player quality) the
  results-only model can't see — but it must enter **via players**, aggregated to the squad,
  not as team xG.
- **Effort:** **medium-high** — player ingestion + squad→player mapping + the aggregation model.

### Track C — Broad scrape (cross-relevant factors only)
- Targets the **top block of §1** keyed to projected national squads: Transfermarkt market
  value + minutes + injuries, Understat xG/xA. **Transfermarkt squad value** is the highest
  value-per-effort free signal (strong, well-established WC predictor, aggregates cleanly).
- **Significance separation built in:** weight each player by `minutes × recency ×
  league_strength × selection_probability`; normalize club output by league coefficient;
  shrink the aggregate toward the team's results-based rating (partial pooling) so club data
  **informs but never overrides** international evidence.
- **Effort/risk:** medium; scraping = maintenance + ToS exposure (Transfermarkt/Understat are
  the practical free targets).

---

## 3. Method to keep the significances separate (the core design)
1. **Hierarchical / partial pooling.** Player-aggregated squad strength is a **prior**;
   international results fit a **team-level deviation** on top. Club data sets the prior's
   mean; international data sets how far each team departs from it. (Strong club squad +
   weak recent international results → regress between, don't blindly trust either.)
2. **Relevance weighting.** Each player's club signal weighted by minutes, recency, league
   strength, and probability of starting — so a benched player in Serie A barely moves it.
3. **League-strength normalization** before aggregation (UEFA/club-Elo coefficients).
4. **As-of-match discipline.** Injuries/form computed strictly pre-kickoff — no leakage.
5. **Backtest on internationals only.** Features come from club data, but every signal is
   validated walk-forward on held-out *international* matches and kept only if RPS improves
   (your standing rule). This is what your sandbox now lets us measure.

---

## 4. Recommended phased scope (cheap→dear, measure at each step)
| Phase | Action | Cost | Effort | Expected payoff |
|---|---|---|---|---|
| 0 | Transfermarkt **squad value** as a team-strength feature; football-data.co.uk club odds as a benchmark | $0 | Low | Best cheap non-results signal; quick backtest |
| 1 | API-Football **player stats + injuries** → player-aggregated squad strength as a prior | ~$19/mo | Med | The real headroom (new signal, via players) |
| 2 | Add Understat/FBref **club xG**, league-normalized, partial-pooled | $0 (scrape) | Med-High | Sharper player quality |
| 3 | International **closing odds** as a benchmark; decide on blending | +$10/mo | Med | Ceiling check; optics call |

Start with **Phase 0** — squad value is the highest payoff-per-dollar, it's the signal your
Elo/DC structurally can't see (a team that just regenerated its squad), and it's a clean,
honest, backtestable test of the whole club→international thesis before spending anything.

## 5. Honest expectation
Player/squad-value signal is the most-cited lever for *international* prediction and is the
one with genuine headroom your earlier (results-only) levers lacked — but the payoff is still
likely *modest* (single-digit-% RPS) because your team-results model already captures most of
what squad quality produces. The win is concentrated exactly where Elo is weakest: squad
turnover, debutants, and post-tournament-cycle teams. Odds would help more numerically but
track the market and clash with the no-betting stance. Everything here is gated by the same
rule: **build it, backtest it on held-out internationals, keep it only if RPS drops.**

---
_Sources: [API-Football pricing](https://www.api-football.com/pricing) · [football-data.co.uk](https://www.football-data.co.uk/data.php) · [Hvattum & Arntzen 2021](https://journals.sagepub.com/doi/10.1177/1471082X20929881) · [player-rating forecasting 2024](https://ideas.repec.org/a/eee/intfor/v40y2024i1p302-312.html) · [WC-model caveats](https://newsletter.wangari.global/p/stop-trusting-ml-predictions-for). Searched 2026-06-22._
