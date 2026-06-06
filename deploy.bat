@echo off
REM ============================================================================
REM  WCPA — one-shot "make it live" pipeline (run on this PC, where the
REM  Postgres DB lives). Pulls the newest results, retrains, re-simulates the
REM  tournament, snapshots everything to .\dist, and pushes it to the CDN.
REM
REM  One-time setup (see LAUNCH.md):
REM    npm install -g wrangler   &&   wrangler login
REM    wrangler pages project create wcpa
REM
REM  Then just run:  deploy.bat        (or schedule it in Task Scheduler)
REM ============================================================================
cd /d %~dp0

echo [1/5] Ingesting latest live results + news...
python run.py ingest live
python run.py ingest news

echo [2/5] Retraining ratings (Elo + draw + Dixon-Coles)...
python run.py train

echo [3/5] Re-simulating the tournament (20,000 runs)...
python run.py simulate 20000

echo [4/5] Exporting the static site to .\dist ...
python run.py export dist
if errorlevel 1 ( echo Export failed — aborting deploy. & exit /b 1 )

echo [5/5] Deploying .\dist to Cloudflare Pages...
call npx wrangler pages deploy dist --project-name=wcpa --commit-dirty=true

echo.
echo Done. Live at your Pages URL (and wcpa26.com once the domain is attached).
