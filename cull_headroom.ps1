# ============================================================
#  Cull headroom + install the silent WCPA deploy
#  Run in Windows PowerShell (right-click > Run with PowerShell,
#  or paste into a PowerShell window). No admin needed.
# ============================================================

Write-Host "`n[1/3] Removing headroom scheduled tasks (the random cmd popups)..." -ForegroundColor Cyan
$hr = Get-ScheduledTask -TaskName 'headroom*' -ErrorAction SilentlyContinue
if ($hr) {
    $hr | ForEach-Object {
        Write-Host "      - removing $($_.TaskName)"
        Unregister-ScheduledTask -TaskName $_.TaskName -Confirm:$false
    }
} else { Write-Host "      (no headroom* tasks found)" }

Write-Host "`n[2/3] Installing 'WCPA silent deploy' (hourly, hidden window)..." -ForegroundColor Cyan
$action  = New-ScheduledTaskAction -Execute 'wscript.exe' `
            -Argument '"C:\Users\sambo\Desktop\WorldCup2026\deploy_silent.vbs"'
# fire once now, then repeat every hour, indefinitely
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Hours 1) `
            -RepetitionDuration ([TimeSpan]::MaxValue)
Register-ScheduledTask -TaskName 'WCPA silent deploy' `
    -Action $action -Trigger $trigger -Force | Out-Null
Write-Host "      installed."

Write-Host "`n[3/3] (Optional) fully uninstall the headroom tool." -ForegroundColor Cyan
Write-Host "      Left commented so it is a deliberate choice. To remove the tool itself,"
Write-Host "      uncomment the two lines below in this file and re-run:"
# Remove-Item -Recurse -Force "$env:USERPROFILE\headroom-env"
# Remove-Item -Recurse -Force "C:\Users\sambo\Desktop\WorldCup2026\.headroom"

Write-Host "`nDone. Popups gone; deploy now runs silently every hour." -ForegroundColor Green
