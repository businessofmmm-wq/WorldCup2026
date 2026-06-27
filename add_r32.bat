@echo off
cd /d %~dp0
echo ===== Adding R32 fixtures =====
python tools\add_r32_fixtures.py
if errorlevel 1 ( echo FAILED - aborting & pause & exit /b 1 )

echo.
echo ===== Regenerating fixtures.json =====
python run.py export dist
if errorlevel 1 ( echo Export failed & pause & exit /b 1 )

echo.
echo ===== Done! =====
pause
