@echo off
REM ============================================================================
REM  WCPA - one-shot "make it live" pipeline (run on this PC, where the
REM  Postgres DB lives). Pulls the newest results, retrains, re-simulates the
REM  tournament (conditioned on played matches), snapshots everything to .\dist,
REM  and pushes it to Cloudflare Pages.
REM
REM  Wrangler notes (learned the hard way - 16h of silent hourly failures):
REM    * `npx --yes` so a fresh wrangler release can NEVER stall a scheduled,
REM      non-interactive run on the "Ok to proceed?" install prompt.
REM    * pinned to wrangler@4 so a future major can't change flag semantics.
REM    * wrangler.toml carries the project name, dist dir and the D1 binding
REM      for the Collapse leaderboard - deploy with NO positional dir.
REM
REM  Then just run:  deploy.bat        (or schedule it in Task Scheduler)
REM ============================================================================
cd /d %~dp0
echo ===== WCPA deploy run started %date% %time% =====

echo [1/5] Ingesting latest live results + news...
python run.py ingest live
python run.py ingest news

echo [2/5] Retraining ratings (Elo + draw + Dixon-Coles + bivariate-Poisson)...
python run.py train

echo [3/5] Re-simulating the tournament (50,000 runs)...
python run.py simulate 50000

echo [4/5] Exporting the static site to .\dist ...
python run.py export dist
if errorlevel 1 ( echo [%date% %time%] Export failed - aborting deploy. & exit /b 1 )

echo [5/5] Deploying .\dist to Cloudflare Pages...
call npx --yes wrangler@4 pages deploy --project-name=wcpa --branch=main --commit-dirty=true
if errorlevel 1 ( echo ===== DEPLOY FAILED %date% %time% ===== & exit /b 1 )

echo ===== Deploy complete %date% %time% - live at https://wcpa26.com =====
