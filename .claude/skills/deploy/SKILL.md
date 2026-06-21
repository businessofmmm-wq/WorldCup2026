---
name: deploy
description: >
  Rebuild and publish the live WCPA site to Cloudflare Pages. Use when asked to
  "deploy", "publish", "push the site live", "update wcpa26.com", or run the full
  ingest -> train -> simulate -> export -> deploy pipeline. Mirrors deploy.bat but
  prescriptive, with a pre-flight gate. Must run on the machine with the local
  Postgres DB and a populated .env.
---

# Deploy WCPA to Cloudflare Pages

Prescriptive runbook for taking the latest data live. Each step is gated — stop
on the first failure and report it rather than continuing.

## Preconditions (verify before starting)
1. Run `scripts/preflight.sh`. It checks: `.env` present, `wrangler.toml` present,
   `dist/` writable, Postgres reachable (`python run.py health`). Do NOT proceed if
   any check fails.
2. Confirm you are on the machine that hosts the local `worldcup` Postgres DB.

## Pipeline (run in order)
1. **Ingest** the newest live results + news:
   `python run.py ingest live` then `python run.py ingest news`
2. **Train** ratings (Elo -> draw -> Dixon-Coles -> bivariate-Poisson):
   `python run.py train`
3. **Simulate** the tournament (50k runs, conditioned on played matches):
   `python run.py simulate 50000`
4. **Export** the static site: `python run.py export dist`
   — If this exits non-zero, ABORT. A broken export must never be deployed.
5. **Pre-deploy gate**: `python run.py audit`. Read the verdict in `AUDIT.md`.
   If the verdict is not GREEN, stop and report the failing checks.
6. **Deploy**:
   `npx --yes wrangler@4 pages deploy --project-name=wcpa --branch=main --commit-dirty=true`
   (`--yes` so a fresh wrangler release can't stall on an install prompt; pinned to
   wrangler@4 so a future major can't change flag semantics.)

## Post-deploy verification
1. `curl -s -o /dev/null -w "%{http_code}\n" https://wcpa26.com/` -> expect `200`.
2. `curl -s https://wcpa26.com/api/meta.json` -> confirm the build timestamp is fresh.
3. Report the live title-odds line from the new `dist/api/report.json`.

## Notes
- Cloudflare auth lives in `.env` (`CLOUDFLARE_API_TOKEN` needs Pages.Edit).
  See `NEXTSTEPS.md` -> "Deploy auth runbook" for the exact token scopes.
- This performs an external action (publishing to production). Always run the
  pre-deploy audit gate (step 5) and surface its verdict to the human before deploying.
