# WCPA — Status & Runbook

_World Cup 2026 Prediction Album. Launched to production 2026-06-08. Pipeline runs
locally against local Postgres **and** in the cloud via GitHub Actions. Last verified
live: 2026-06-16._

## 🟢 Live
- **https://wcpa26.com** (apex) + **www** + **wcpa.pages.dev** — Cloudflare Pages, cert active. `/` and `/api/*` serve the album.
- Updates within ~5 min during matches, ~20 min otherwise; full 50k re-sim every 6 h.

## Stack
- **Engine** (pure-Python + Postgres): Elo → Dixon-Coles → **bivariate-Poisson** (locked; `lambda3` coupling), ensemble **T=0.85**, 50k Monte-Carlo conditioned on played results. CLI = `run.py` (argparse subcommands).
- **Data sources** (`sources/`):
  - `footballdata.py` — **live results, primary** (football-data.org v4, comp `WC`). One request pulls all matches, classified by status; backfills any finished game a missed poll skipped.
  - `sportsdb.py` — fallback when no token/feed error; also owns the team-name canonicalisation `NAME_MAP` (e.g. `Cape Verde Islands → Cape Verde`).
  - `results.py` (martj42 history), `statsbomb.py` (xG).
- **Front-end** (`viz/static/`): album UI; Groups Prediction⇄Reality (Reality = full standings table + form); Bracket page with one chronological **All** matches list (results+upcoming); Match Lab; Collapse; Intel; Rankings.
- **Collapse leaderboard**: Cloudflare D1 `wcpa-runs` bound in `wrangler.toml`; replay-verified, ≤8 handles/network/day.

## Deploy & automation
- **Local**: `deploy.bat` (or `python manage.py deploy`) = ingest live → train → simulate 50k → export `dist` → `npx --yes wrangler@4 pages deploy`. Optional Task Scheduler `WCPA-deploy-hourly` (interactive logon; auto-expires 2026-07-20).
- **Cloud** (`.github/workflows/`, branch `master`):
  - `wcpa-deploy.yml` — full rebuild, cron `0 */6 * * *` + manual.
  - `wcpa-refresh.yml` — gated cadence: ~5 min in a match window (kickoff −15→+175), ~20 min steady; cron `*/5`.
  - `wcpa-publish.yml` — rebuild+deploy on push to `master` touching `viz/**`, `run.py`, `config.py`, `models/**`, `schema.sql`.
  - (Legacy `full.yml`/`refresh.yml` removed — they duplicated the above.)

## Deploy auth runbook (Cloudflare — account businessofmmm@gmail.com)
- **Account ID**: `b6e98504a28df02312909736db606064` (owns Pages project `wcpa`). Must match in `.env` **and** GitHub secret `CLOUDFLARE_ACCOUNT_ID`.
- **API token** must have **Account · Cloudflare Pages · Edit** (+ `User · Memberships · Read`, `User · User Details · Read`). Read-only fails at `upload-token` with error 10000.
- **Secrets** (local `.env` + GitHub Actions): `WORLDCUP_DATABASE_URL`, `WCPA_FOOTBALLDATA_TOKEN`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`. Set in GitHub via `gh secret set <NAME> --body …` or repo Settings → Secrets. `.env` is gitignored.
- **DNS**: zone `wcpa26.com`, apex + www `CNAME → wcpa.pages.dev` (proxied). DNS edits need the zone-scoped `cfat…` token (Session1.txt), not the Pages token.

## Title odds (live, 50k)
Argentina 20.8% · Spain 14.7% · Brazil 12.4% · England 9.5% · France 7.3% · Portugal 6.8%.

## Open items
- [ ] **Verify cloud deploys** are green (today's publish was local-PC; confirm the GitHub `CLOUDFLARE_API_TOKEN` secret has Pages:Edit).
- [ ] **Re-run `python run.py audit`** — the last GREEN (14 checks, ~786 req/s) predates the feed swap, UI and workflow changes.
- [ ] **Knockout kickoff times**: harvest once R32 pairings are set → extend `models/schedule_2026.KICKOFFS_UTC` (group stage fully mapped). Bracket page auto-leads with matches until then.
- [ ] Real **SHOP affiliate IDs** in `viz/static/app.js` (placeholders) → re-export.
- [ ] _Optional_: Turnstile on leaderboard · Cloudflare Email Routing for hello@wcpa26.com (no MX yet) · diagonal-inflated bivariate-Poisson as a 3rd `GOALS_MODEL`.

## APP/ — Goal Theatre (separate, in repo)
Single-file `APP/index.html`: reconstructs how a goal happened (pass/carry/shot replay) on a StatsBomb-schema pitch; live match rail off `wcpa26.com/api`. Full positional replay needs StatsBomb (historical) or a paid live feed; free football-data gives score/scorer/minute only. Next: StatsBomb match → `GOALS` mapper.

## Recently shipped
- Live feed → football-data.org with all-status single-fetch + backfill (fixes late-night games being missed); even refresh cadence; duplicate workflows removed.
- Name fix `Cape Verde Islands → Cape Verde` (+ one-off `fix_cape_verde.py` for orphan rows).
- UI: chronological All matches view, Reality standings table + form, iPhone Safari sizing/spacing pass.
- Cloudflare account-ID corrected; deploy-auth runbook captured above.
- Engine: sim conditions on played matches; frozen pre-kickoff model record (`predictions`); `refresh` refits BP; OG card + about.html dark theme.
