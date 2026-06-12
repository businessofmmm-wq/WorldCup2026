# WCPA — Launch status & runbook

_World Cup kicks off 11 Jun 2026. **WCPA launched to production 2026-06-08** —
Samuel chose to publish ~15.5h ahead of the original 9 Jun 08:00 AEST embargo
(explicit override, confirmed via prompt). All pipeline commands run locally
against the local Postgres._

## 🟢 LIVE
- **https://wcpa26.com** — apex; Cloudflare Pages custom domain **active**, cert
  **active** (Google CA). `/` + `/api/*` serve the album.
- **https://www.wcpa26.com** — attached to Pages + CNAME → wcpa.pages.dev
  (proxied); provisioning→active.
- **https://wcpa.pages.dev** — the Pages production URL.
- Audit: **GREEN** — 14 checks, 0 fail / 0 warn, load test passed (~786 req/s).

## Infrastructure (Cloudflare — account businessofmmm@gmail.com, id b6e9…6064)
- **Pages project `wcpa`** (wcpa.pages.dev). Deploy:
  `npx wrangler pages deploy dist --project-name=wcpa` (or `deploy.bat`).
- **DNS** (zone `wcpa26.com`, same CF account):
  - apex `CNAME wcpa26.com → wcpa.pages.dev` (proxied) — replaced the GoDaddy
    "coming soon" parking record (`A → 13.248.243.5`), deleted 2026-06-08.
  - `CNAME www.wcpa26.com → wcpa.pages.dev` (proxied).
  - No MX/TXT/email records.
- **Tokens:** the wrangler OAuth token (`%APPDATA%\xdg.config\.wrangler`) has
  `pages:write` + `zone:read` but **no `dns_records` scope** — DNS edits use the
  dedicated **`cfat…` "Edit zone DNS" token in `Desktop\Session1.txt`** (~line 11,
  53 chars). NB that token **fails** `/user/tokens/verify` (it's zone-scoped) but
  **works** for DNS API calls.

## Match-day freshness — AUTOMATED
- **Task Scheduler task `WCPA-deploy-hourly`**: runs `deploy.bat` (ingest live →
  retrain → simulate 50k → export → deploy) **hourly**, output →
  `deploy_scheduled.log`. **Auto-expires 2026-07-20** then self-deletes.
  - Runs **only while the PC is on + Samuel is logged in** (Interactive logon, no
    stored password); a brief console window flashes each hour. For silent /
    logged-out runs, tick "Run whether user is logged on or not" + "Hidden" in
    Task Scheduler (needs the Windows password).
  - Manage: `Get-ScheduledTask WCPA-deploy-hourly` / `Unregister-ScheduledTask`.

## Shipped 2026-06-12 (mid-tournament hardening pass)
- [x] **Hourly deploy un-hung** — wrangler 4.100.0's release made bare `npx wrangler`
      prompt "Ok to proceed?" in the scheduled task → ~16 h of silent failed deploys
      overnight. `deploy.bat` now uses `npx --yes wrangler@4` (never prompts, major
      pinned) + start/finish/FAILED log markers. Verified: the 18:00 task run
      deployed clean end-to-end.
- [x] **Sim now conditions on played matches** (`models/tournament.py`): real WC-2026
      results (and shootout winners, once KOs start) are locked into every simulated
      tournament; only the future is randomised. Mexico 97%+ to advance after the
      opener, as it should be.
- [x] **Ingest is duplicate/clobber-proof** (`sources/sportsdb.py`): TheSportsDB
      UTC dates vs schedule local dates created ghost fixtures (SK–CZ appeared
      twice; ~20 late-UTC kickoffs would have followed). Now: name canonicalisation
      (USA→United States, Curacao→Curaçao…), ±1-day fixture claiming, and a real
      score is never overwritten with NULL by the flaky feed. One-time DB merge done.
- [x] **Honest model record**: every export freezes pre-kickoff calls into the
      `predictions` table (`server.log_upcoming_calls`); completed matches are graded
      against the *frozen* call, not a hindsight-refit one (`frozen_call` flag in
      fixtures.json; the two pre-freeze results fall back to live grading).
- [x] **Collapse daily leaderboard LIVE** — see LEADERBOARD-SETUP.md status. D1
      `wcpa-runs` + wrangler.toml binding; submit verified/persisted/ranked on prod;
      forged + oversized submissions rejected; ≤8 handles per network per day.
- [x] `refresh` now refits **BP** (chained onto the DC step in `cmd_refresh`).
- [x] Front-end: scrollspy fixed (observed two dead ids, missed three live ones);
      Match Lab's 1.27 MB matrix now lazy-loads on approach instead of at boot;
      Results tab newest-first; dead Quantum-Tactics-Lab code (~250 lines) culled
      from app.js and its 74 dead files from the export (deploy: ~190→35 files);
      collapse.js surfaces real submit errors + "↑ board" submits saved daily runs.
- [x] **OG share card + about.html re-skinned dark** to match the album theme.

## Still open (post-launch, non-blocking)
- [ ] Real **SHOP affiliate IDs** in `viz/static/app.js` (placeholders now) →
      re-export + redeploy.
- [ ] _(Optional)_ **Turnstile** on the leaderboard (LEADERBOARD-SETUP.md step 3) —
      the replay verifier + per-network cap already hold the line.
- [ ] _(Optional)_ `security.txt` lists hello@wcpa26.com but the zone has no MX —
      enable Cloudflare Email Routing → forward to the real inbox.
- [ ] _(Optional)_ Diagonal-inflated bivariate Poisson as a 3rd `GOALS_MODEL`.
- [ ] Knockout kickoff times: harvest TheSportsDB once R32 pairings are set and
      extend `models/schedule_2026.KICKOFFS_UTC` (group stage is fully mapped).

## The engine (settled this cycle)
- Goals model **bivpois** locked (beat Dixon-Coles on the full 2018 backtest:
  RPS 0.1686 vs 0.1691; `lambda3` ≈ +0.06–0.07 real coupling). Tuned + calibrated
  (ensemble **T=0.85**). 50k authoritative sim: **Argentina ~19%, Spain ~16%,
  Brazil ~14%, England ~8%, France ~8%, Portugal ~7%**.
- The quantum lens — 50k sampled futures held in superposition; bivariate-Poisson
  `lambda3` coupling; variance reduction to expand efficiently; **information →
  matter** via the static album export — is faithful to the engine; keep building
  through it.
