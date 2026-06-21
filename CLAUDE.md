# CLAUDE.md

## Project
World Cup 2026 prediction engine (WCPA): pure-Python statistical models (Elo →
Dixon-Coles → bivariate-Poisson → Monte-Carlo) over a local PostgreSQL DB, with a
static site exported to Cloudflare Pages at https://wcpa26.com. Built for one
maintainer; the CLI is the primary interface.

## Tech stack
- Engine: pure Python 3.12+ (no numpy/scipy/pandas). Deps are deliberately tiny:
  `requests`, `psycopg[binary]` (+ `Pillow` for the build-time OG card only).
- Data: PostgreSQL (`worldcup` DB). Schema is version-controlled in `schema.sql`.
- Frontend: static HTML/JS in `viz/static/`, served by stdlib `http.server` in dev,
  exported to `./dist` for the CDN. No framework.
- Deploy: Cloudflare Pages + a few Workers (`functions/`); GitHub Actions cron.

## Key files
- `run.py` — single CLI entry point (argparse subcommands). Start here.
- `config.py` — all tunables + the no-dependency `.env` loader. No secrets in source.
- `db.py` — PostgreSQL wrapper (psycopg).
- `models/` — prediction engines (`elo`, `poisson`/Dixon-Coles, `bivpoisson`,
  `draw_model`, `predict`, `tournament`, `backtest`, `variance`, `tune`).
- `sources/` — data ingestion (`footballdata` is the primary live feed; `sportsdb`
  fallback + name canonicalisation; `results` history; `statsbomb` xG).
- `viz/` — `export.py` (static build) + `server.py` (dev) + `static/` (UI).
- `tools/` — `audit.py` (security/hygiene gates), `recalibrate.py`, `backtest_agent.py`.
- `schema.sql` / `schema_runs.sql` — DB schema (never drop columns; init is idempotent).

## CLI cheat-sheet
```
python run.py init | ingest [results|live|news|xg|all] | train
python run.py predict HOME AWAY [--home] | simulate [runs] | groups | rankings [n]
python run.py backtest [year] [--compare] [--refit N] | tune | calibrate
python run.py refresh | export [dir] | audit
```

## Conventions
- Absolute imports within the package; lazy imports in command handlers for fast start.
- Models are stateless — all state lives in the DB.
- Sources are idempotent — safe to re-run.
- UTF-8 stdout is forced at entry (Windows cp1252 safe).
- Graceful degradation: return None/empty on source failure rather than crashing.

## Constraints
- Keep the dependency set tiny — do not add numpy/scipy/pandas or a web framework.
- Never commit `.env`, `.venv/`, `dist/`, `*.pt` model weights, or `*.log` (all gitignored).
- Never bake credentials into source — read them from the environment / `.env`.
- `schema.sql` is additive only; never delete columns.

## Skills (.claude/skills/)
- `/deploy` — rebuild + push the live site (ingest → train → simulate → export → Pages).
- `/backtest-tune` — leakage-free accuracy backtest, tune, and recalibrate the model.

## Validation
- Run `python run.py audit` (writes `AUDIT.md`) before any deploy — secret scan, SQL
  parameterisation, headers, compile-all, load test.
- `python run.py backtest 2022` is the primary accuracy gate (RPS, lower is better).

## Reference docs (load on demand, don't inline)
`README.md` overview · `ARCHITECTURE.md` design · `NEXTSTEPS.md` runbook/status ·
`BACKTEST.md` methodology · `LEADERBOARD-SETUP.md` / `FOOTBALLDATA-SETUP.md` setup.

---
_Python 3.12+ · last reviewed 2026-06-21._
