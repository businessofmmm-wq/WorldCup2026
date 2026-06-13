@echo off
REM  WCPA maintenance terminal - double-click to open the console
cd /d %~dp0
python manage.py %*
pause
