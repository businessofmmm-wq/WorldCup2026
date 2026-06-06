# World Cup '26 — Prediction Album (dashboard)

A **retro sticker-album** dashboard over the prediction engine. Pure standard
library — no Flask, no chart library, no build step. It serves one page plus a
small JSON API straight off the live Postgres ratings, the ensemble match
predictor and the Monte-Carlo sim feeds.

## Run

```powershell
# from the project root
python run.py viz              # http://localhost:8008
python run.py viz 9000         # custom port
# or directly:
python viz/server.py --port 8008
```

Make sure the engine has data first (`python run.py health` should show
matches/ratings; if not: `python run.py ingest all && python run.py train &&
python run.py simulate`). PostgreSQL must be running.

## What's on the page

| Page | Source |
|---|---|
| **Who Lifts It** — title odds, podium, road-to-final | `data/sim_report.json` |
| **The Wallchart** — official R32→Final bracket + the model's chalk path | `/api/bracket` (live predictor) |
| **Group Pages** — 12 groups, advance odds, flags | `data/group_adv.json` |
| **Power Rankings** — live Elo + click-to-expand trajectory | `team_ratings` / `elo_history` |
| **Match Lab** — pick any two of the 48, get a live ensemble prediction | `/api/predict` |
| **Team Intel** — RSS clippings auto-tagged & flagged | `news` table |
| **The Method** — held-out accuracy, pipeline, sources | `BACKTEST.md` figures |

## API

`/api/meta` · `/api/report` · `/api/groupadv` · `/api/rankings?n=` ·
`/api/history?team=` · `/api/predict?home=&away=&neutral=` · `/api/news?team=&n=` ·
`/api/bracket`

## Design

Blokecore / retro-terrace: cream paper with grain + halftone, die-cut foil
stickers, terrace type (Anton / Staatliches / Space Grotesk via Google Fonts).
National flags are public-domain images from [flagcdn](https://flagcdn.com)
(`viz/flags.py` maps each team to its ISO-2 code). Everything else is
hand-rolled CSS + SVG in `viz/static/`.
