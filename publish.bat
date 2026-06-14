@echo off
REM ==== WCPA one-click publish ====
REM Double-click this to push your edits live. That's the whole job.
cd /d "C:\Users\sambo\Desktop\WorldCup2026"
echo Saving and publishing your changes...
git add -A
git commit -m "Update site %date% %time%"
git push origin master
echo.
echo ============================================
echo  Pushed. The live site rebuilds in ~1-2 min.
echo ============================================
pause
