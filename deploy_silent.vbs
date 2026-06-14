' WCPA silent deploy launcher
' Runs the full non-interactive manage.py deploy with NO visible window.
' (ingest live+news -> retrain -> simulate 50k -> export -> verify -> wrangler push)
Set sh = CreateObject("WScript.Shell")
sh.CurrentDirectory = "C:\Users\sambo\Desktop\WorldCup2026"
sh.Run "cmd /c python manage.py deploy >> deploy_scheduled.log 2>&1", 0, False
