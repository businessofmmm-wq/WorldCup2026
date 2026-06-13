@echo off
REM ===========================================================================
REM  WCPA - one unified deploy. Rebuilds .\dist from source + live data, VERIFIES
REM  the exported CSS/JS byte-match source (so a stale or truncated stylesheet can
REM  never ship), then pushes to Cloudflare Pages. Replaces deploy.bat +
REM  deploy-frontend.bat - everything ships from this one script.
REM
REM    deploy.bat          ship current code + data   (export -> verify -> deploy)
REM    deploy.bat full     also ingest live+news, retrain, re-simulate 50k first
REM ===========================================================================
cd /d %~dp0
echo ===== WCPA deploy %date% %time% =====

if /I "%~1"=="full" call :refresh
if errorlevel 1 goto :fail

echo [export] rebuilding .\dist from source (static + API + cache-bust stamps)...
python run.py export dist
if errorlevel 1 goto :fail

echo [verify] confirming exported CSS/JS match source (no stale/truncated assets)...
fc /B viz\static\style.css dist\style.css >nul
if errorlevel 1 goto :stale
fc /B viz\static\app.js dist\app.js >nul
if errorlevel 1 goto :stale
findstr /C:"</html>" dist\index.html >nul
if errorlevel 1 goto :stale

echo [deploy] pushing .\dist to Cloudflare Pages...
call npx --yes wrangler@4 pages deploy --project-name=wcpa --branch=main --commit-dirty=true
if errorlevel 1 goto :fail

echo ===== Done %date% %time% - live at https://wcpa26.com  (hard-refresh: Ctrl+F5) =====
pause
exit /b 0

:refresh
echo [refresh] ingest live + news, retrain, re-simulate 50k...
python run.py ingest live
if errorlevel 1 exit /b 1
python run.py ingest news
if errorlevel 1 exit /b 1
python run.py train
if errorlevel 1 exit /b 1
python run.py simulate 50000
if errorlevel 1 exit /b 1
exit /b 0

:stale
echo ===== ABORTED: exported dist looks stale/truncated - nothing deployed. =====
pause
exit /b 1

:fail
echo ===== FAILED %date% %time% - nothing deployed. =====
pause
exit /b 1
