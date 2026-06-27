# Collapse daily leaderboard — one-time setup

> **STATUS 2026-06-12: DONE & LIVE.** D1 `wcpa-runs` created
> (id `67c42d39-f3ab-4a72-b443-3facbad89416`, region OC), schema applied remotely,
> bound to the Pages Functions via `wrangler.toml` (option B). Verified on prod:
> a real run submits, persists and ranks; a forged claim returns
> `verification mismatch`; oversized ops are rejected; ≤8 handles per network
> per day (sha256(day|ip) — no raw IPs stored). Only Turnstile (step 3) remains
> optional/open.

The Collapse run game works fully without any of this — Daily Challenge,
Free Play, run history and the run card are all client-side. This enables the **global
daily board**: a Cloudflare D1 database + the two Pages Functions in `functions/`.

Everything here needs your Cloudflare auth (`wrangler login` once). The live hourly
`deploy.bat` is **unaffected** until you finish step 2 — the Functions deploy with the
rest of the site and already VERIFY every run (replaying it server-side); they just
return "verified, not persisted" and the board stays empty until D1 is bound.

## 1. Create the database + table
```sh
wrangler d1 create wcpa-runs
#   → copy the printed database_id
wrangler d1 execute wcpa-runs --remote --file=schema_runs.sql
```

## 2. Bind D1 to the Pages Functions  (pick ONE)

**A — Dashboard (recommended; does not touch deploy.bat).**
Pages → **wcpa** → Settings → Functions → **D1 database bindings** →
add  **Variable name `DB` → wcpa-runs**.  Done. Next hourly deploy persists runs.

**B — wrangler.toml (IaC).** Create `wrangler.toml` at the repo root:
```toml
name = "wcpa"
pages_build_output_dir = "dist"
compatibility_date = "2026-06-01"

[[d1_databases]]
binding = "DB"
database_name = "wcpa-runs"
database_id = "PASTE_THE_ID_FROM_STEP_1"
```
⚠ If you add this file, run one manual `wrangler pages deploy dist --project-name=wcpa
--branch=main --commit-dirty=true` and confirm it succeeds **before** trusting the hourly
task (some wrangler versions prefer `wrangler pages deploy` with no positional dir when
`pages_build_output_dir` is set). Option A avoids this entirely.

## 3. (Optional) Turnstile — block bot submissions
1. Cloudflare dashboard → Turnstile → add a widget for `wcpa26.com`; copy the **site key**
   and **secret key**.
2. Put the site key in `viz/static/collapse.js`:  `const TURNSTILE_SITEKEY = '0x...';`
3. Store the secret:  `wrangler pages secret put TURNSTILE_SECRET --project-name wcpa`

Until a secret is set the Function skips Turnstile (so the board can go live first and
add bot defense later). The CSP already allows `challenges.cloudflare.com`.

## How the anti-cheat works
The board only accepts **Daily Challenge** runs. Each submission carries the day's seed
and the per-match operator choices. `functions/api/run/submit.js` re-runs them through the
exact same `viz/static/collapse-core.js` the browser used, against that day's frozen
`api/daily.json` snapshot, and rejects anything whose recomputed round + margin don't match
the claim. Score = how far you got (dominant) + a difficulty bonus for weaker nations +
goal margin. Best run per handle per day is kept.

## Verify after setup
```sh
# a deployed valid run should return {"ok":true,"verified":true,"rank":N}
# the board:
curl "https://wcpa26.com/api/leaderboard?day=$(date -u +%F)"
```
