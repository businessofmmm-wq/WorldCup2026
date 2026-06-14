# WCPA — Cloud Automation Scope

Move the wcpa26.com pipeline off your desktop into GitHub Actions so the site
updates itself with no machine of yours running and no human in the loop.

---

## 1. Goal

Today the whole site depends on your PC: local Postgres, the engine, `wrangler`,
and Task Scheduler all run on Windows. The site is only live and fresh while your
machine is on, awake, and online — and updates need either you or a scheduled task
popping windows.

Target: a final whistle blows → a cloud cron tick ingests the result, re-sims, and
pushes the updated site a few minutes later. PC off, fully autonomous, observable,
with email alerts on failure. Your local `manage.py` stays as the manual override.

---

## 2. Why this is a small job here

The codebase was already designed for it. Three things that would normally be the
hard parts are already done:

- **DB is env-driven.** `config.py` reads `WORLDCUP_DATABASE_URL` / `DATABASE_URL`
  and falls back to `.env` locally. Pointing at cloud Postgres = setting one secret.
  No code change.
- **Dependencies are tiny.** Runtime is just `requests` + `psycopg[binary]`
  (pure-Python models, no numpy/scipy/pandas). The opencv/ultralytics/YOLO stack is
  local-only and never imported by the deploy path — it stays off CI entirely.
- **All data sources are public, no keys.** martj42 results CSV, TheSportsDB (public
  key `3`), StatsBomb open data, RSS news. So a **cold cloud DB rebuilds itself** by
  running `init → ingest → train` — there is **no data migration / pg_dump to do**.

The Collapse leaderboard's Cloudflare **D1** database already lives on Cloudflare and
is handled by `wrangler pages deploy` — nothing to migrate there either.

---

## 3. Target architecture

```
GitHub Actions (cron)                         Cloud
  ├─ checkout repo                             ┌────────────────────┐
  ├─ pip install requests psycopg  ──reads──▶  │ Neon Postgres      │  (free tier)
  ├─ python run.py ingest live/news ──writes─▶ │  matches/ratings/… │
  ├─ python run.py train + simulate            └────────────────────┘
  ├─ python run.py export dist                 ┌────────────────────┐
  └─ npx wrangler pages deploy   ──publishes─▶ │ Cloudflare Pages   │  wcpa26.com
                                               │  + D1 (leaderboard)│
                                               └────────────────────┘
```

Your desktop is no longer in the diagram. `manage.py` still works locally as a manual
lever whenever you want to poke at it.

---

## 4. Cadence design (two workflows)

Running a full 50k simulation every few minutes is wasteful, so split it:

- **`refresh.yml` — frequent, light.** On a cron (e.g. every 10 min on match days),
  ingest live + news, light re-sim (`REFRESH_RUNS=1500`, antithetic — already the
  configured refresh mode), export, deploy. Fast turnaround after results land.
- **`full.yml` — periodic, heavy.** A few times a day (or nightly), full
  `ingest all → train → simulate 50000 → export → deploy` for the high-fidelity
  numbers. This is exactly today's `manage.py deploy`.
- **Manual trigger** (`workflow_dispatch`) on both, so you can force a deploy from the
  GitHub UI / phone anytime — that becomes your "go full deploy now" button.

GitHub also emails you automatically when a scheduled run fails; we can add a richer
ping (e.g. a Discord/Slack webhook) if you want.

---

## 5. Who does what

**I build (from here, all code, committed to the repo):**

- `.github/workflows/refresh.yml` and `full.yml` (cron + manual dispatch).
- A cold-start bootstrap step (run `init` + `ingest all` + `train` if the DB is empty)
  so the first cloud run populates Neon from public data with no manual seeding.
- `.env.example` / docs update for the new env vars.
- Optional failure-alert step.
- Verify the export→deploy path runs clean on a Linux runner.

**You do once (≈15 min, because I must not handle credentials):**

1. Create a free **Neon** project → copy its connection string.
2. Create a **Cloudflare API token** (Pages: Edit) → copy it, plus your account ID.
3. Paste three values into **GitHub → repo → Settings → Secrets → Actions**:
   `WORLDCUP_DATABASE_URL`, `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`.
4. (After it's confirmed working) delete the local **"WCPA silent deploy"** task so the
   two don't both publish.

---

## 6. Trade-offs / limits (honest)

- **Cron latency.** GitHub scheduled jobs fire on ~5-min minimum granularity and can be
  delayed a few minutes under load, so expect ~5–15 min from final whistle to live
  update. Fine for a prediction site; if you ever want near-instant, the upgrade is a
  tiny always-on worker (Cloudflare Cron Triggers / a $5 VPS) — out of scope for now.
- **News history.** RSS only serves recent items, so historical news rebuilt on a cold
  DB starts from "now." Cosmetic; match data is fully reconstructable.
- **Free-tier limits.** Neon free tier and GitHub Actions free minutes comfortably fit
  this workload; worth a glance if cadence gets very aggressive.

---

## 7. Sequencing

1. I write both workflows + bootstrap + docs and commit (no secrets needed yet).
2. You provision Neon + Cloudflare token and add the 3 GitHub secrets.
3. We trigger `full.yml` manually once → it cold-builds Neon and deploys → verify site.
4. Enable the crons; retire the local "WCPA silent deploy" task.

Step 1 is the bulk of the work and I can do it now. Steps 2–4 are quick and gated on
your accounts.

---

## 8. Open decisions for you

- **Cadence:** how often on match days (every 10 min light / nightly full is my
  default) and whether to deploy on every git push too.
- **Alerts:** GitHub's default failure emails, or add a Discord/Slack webhook?
- **Latency:** accept ~5–15 min cron latency, or do you want the always-on-worker
  upgrade later for near-instant updates?
