# World Cup 2026 — Prediction & Live Data Engine

A statistical engine that ingests every digitised international football data
source it can reach, fits modern rating models, and predicts the 2026 FIFA
World Cup — refreshed continuously from a live results + news feed.

Pure Python (only `requests` + `psycopg`); backs onto the local PostgreSQL
`worldcup` database. No numpy/scipy/pandas — the models are implemented from
scratch so the whole thing runs anywhere.

## What it tracks
| Layer | Source | What it gives |
|-------|--------|---------------|
| Historical results | martj42/international_results | Every men's international since 1872 (~49k matches) |
| Live fixtures/results | TheSportsDB (free) | Upcoming + just-finished World Cup matches |
| Expected goals (xG) | StatsBomb open data | Shot-level xG for past World Cups |
| News inflow | BBC / Guardian / Sky / ESPN RSS | Team-tagged, flagged (injury/suspension/lineup/form/transfer) |
| Penalty shootouts | martj42 shootouts | Knockout tiebreak history |

## The models
1. **International Elo** — World Football Elo conventions: tournament-weighted
   K-factor, home advantage (0 on neutral grounds), goal-difference multiplier.
   Replays all 49k matches; stores ratings + full history.
2. **Dixon-Coles goals model** — Poisson attack/defence + home advantage, fit by
   maximum likelihood (gradient ascent) with exponential time-decay and L2
   shrinkage. Produces a full scoreline grid with the low-score (tau) correction.
3. **Ensemble** — blends the Elo 1X2 (via a data-fitted *ordered-logit* draw
   model) and the Dixon-Coles 1X2, then applies a fitted calibration temperature.
   Produces win/draw/loss + expected goals + most-likely scoreline.
4. **Monte Carlo tournament** — simulates the 48-team / 12-group 2026 format over
   the **official R32 seeding bracket** (FIFA Annex C) thousands of times for
   title odds.
5. **Backtest** — a leakage-free walk-forward that scores every model on held-out
   history (RPS / log-loss / Brier / calibration). Every parameter is tuned
   against it; see [`BACKTEST.md`](BACKTEST.md).

## Quick start
```powershell
python run.py init            # create schema in the worldcup DB
python run.py ingest all      # historical + live + news + xG
python run.py train           # fit Elo + draw model + Dixon-Coles
python run.py backtest 2018   # leakage-free accuracy backtest (RPS/etc)
python run.py tune            # grid-tune params on held-out RPS
python run.py calibrate       # fit the ensemble temperature
python run.py rankings 25     # current world order
python run.py predict Brazil Argentina
python run.py groups          # official 2026 final draw + seeds
python run.py simulate 50000  # title odds (official bracket)
python run.py refresh         # one inflow cycle: live+news -> retrain -> resim
python run.py loop 1800       # keep predictions live, every 30 min
```

## Status
Engine + data + models + CLI complete and **measured**: the match model is
backtested leakage-free, tuned and calibrated on ~8,000 held-out internationals
(RPS 0.167 / log-loss 0.857 over 2018+, calibrated to ~1%; see
[`BACKTEST.md`](BACKTEST.md)). The 48-team field in `models/field_2026.py` is the
**official 2026 final draw** (`OFFICIAL_GROUPS`) and the knockout stage uses the
**official R32 seeding bracket** (`R32` / `BRACKET`, FIFA Annex C) — both
structural to-dos are now done.

Configuration (data sources, model params, DB URL) lives in `config.py`;
backtest-tuned overrides live in `data/tuned_params.json` (delete to revert).
**Next session: the visual layer** (dashboard over `predictions`, `sim_results`,
`team_ratings`, `news` — a small stdlib-HTTP/HTML or Streamlit front end).
