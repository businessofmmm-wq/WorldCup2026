@echo off
REM  WCPA control window - run EVERYTHING from here (status, refresh, deploy,
REM  watch, pipeline, dashboard). Double-click to open the menu.
cd /d %~dp0
python manage.py %*
pause
