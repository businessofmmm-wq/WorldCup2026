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
3. **Ensemble** — blends the Elo 1X2 and the Dixon-Coles 1X2 into the published
   win/draw/loss + expected goals + most-likely scoreline.
4. **Monte Carlo tournament** — simulates the 48-team / 12-group 2026 format
   (groups → 8 best thirds → R32 → final) thousands of times for title odds.

## Quick start
```powershell
python run.py init            # create schema in the worldcup DB
python run.py ingest all      # historical + live + news + xG
python run.py train           # fit Elo + Dixon-Coles
python run.py rankings 25     # current world order
python run.py predict Brazil Argentina
python run.py groups          # official 2026 final draw + seeds
python run.py simulate 20000  # title odds
python run.py refresh         # one inflow cycle: live+news -> retrain -> resim
python run.py loop 1800       # keep predictions live, every 30 min
```

## Status
Engine + data + models + CLI complete and validated on real data. **Next
session: the visual layer** (dashboard over `predictions`, `sim_results`,
`team_ratings`, `news` — likely a small FastAPI/HTML or Streamlit front end).

Configuration (data sources, model params, DB URL) all live in `config.py`.
The 48-team field in `models/field_2026.py` is the **official 2026 final draw**
(`OFFICIAL_GROUPS`); the simulator uses it as a fixed group draw. Remaining
upgrade: encode the official R32 seeding map (knockout pairings are still
bracket-randomised).
