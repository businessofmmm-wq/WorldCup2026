#!/usr/bin/env python
"""
WCPA — wcpa26.com maintenance terminal
======================================

An interactive console for running the World Cup '26 site through the
tournament month: check the live site's freshness, pull the newest
results/news and re-simulate, push to Cloudflare, or sit in a match-day
watch loop. Stdlib-only (no extra deps) — it just drives the existing
`run.py` engine and the deploy scripts.

    python manage.py            # open the menu
    python manage.py status         # one-shot status, then exit
    python manage.py refresh        # one-shot local refresh, then exit
    python manage.py deploy         # one-shot FULL deploy: ingest live + retrain +
                                    #   simulate 50k + export + verify + push
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
import datetime as dt
from urllib.request import urlopen, Request
from urllib.error import URLError

# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
PROD = "https://wcpa26.com"
WC_START = dt.date(2026, 6, 11)         # opening match
WC_END = dt.date(2026, 7, 19)           # final
LIVE_MIN = 125                          # a match is "live" for ~125 min after kickoff

# enable ANSI colours on Windows 10+ consoles
if os.name == "nt":
    os.system("")
def _c(code): return "" if os.environ.get("NO_COLOR") else code
DIM, BOLD, RED, GRN, YEL, CYA, MAG = (_c(f"\033[{n}m") for n in
                                      ("2", "1", "31", "32", "33", "36", "35"))
RST = _c("\033[0m")
def banner(s): return f"{BOLD}{CYA}{s}{RST}"
def ok(s):     return f"{GRN}{s}{RST}"
def warn(s):   return f"{YEL}{s}{RST}"
def bad(s):    return f"{RED}{s}{RST}"

PY = sys.executable or "python"


# --------------------------------------------------------------------------- #
#  process helpers — everything runs from the project root
# --------------------------------------------------------------------------- #
def run_cmd(args, *, shell=False, label=None):
    """Run a command, streaming its output live. Returns the exit code."""
    if label:
        print(f"\n{DIM}$ {label}{RST}")
    try:
        return subprocess.run(args, cwd=ROOT, shell=shell).returncode
    except KeyboardInterrupt:
        print(warn("\n  (interrupted)"))
        return 130
    except FileNotFoundError as e:
        print(bad(f"  command not found: {e}"))
        return 127


def engine(*args, label=None):
    """Run `python run.py <args>` in the project venv."""
    return run_cmd([PY, "run.py", *args], label=label or "run.py " + " ".join(args))


def confirm(prompt):
    try:
        return input(f"{YEL}{prompt}{RST} ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def pause():
    try:
        input(f"\n{DIM}— press Enter to return to the menu —{RST}")
    except (EOFError, KeyboardInterrupt):
        pass


# --------------------------------------------------------------------------- #
#  live-site status (reads the deployed JSON the site itself serves)
# --------------------------------------------------------------------------- #
def fetch_json(path, timeout=8):
    url = PROD + path
    try:
        req = Request(url, headers={"User-Agent": "wcpa-manage/1.0",
                                    "Cache-Control": "no-cache"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8")), None
    except (URLError, TimeoutError, ValueError, OSError) as e:
        return None, str(e)


def rel_time(iso):
    if not iso:
        return "—"
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    mins = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 60
    if mins < 0:
        return "in the future"
    if mins < 2:
        return "just now"
    if mins < 60:
        return f"{int(mins)} min ago"
    if mins < 48 * 60:
        return f"{int(mins / 60)} h ago"
    return f"{int(mins / 1440)} d ago"


def _kick(iso):
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def tournament_day():
    today = dt.date.today()
    if today < WC_START:
        return f"{(WC_START - today).days} days until kickoff ({WC_START:%a %d %b})"
    if today > WC_END:
        return "tournament complete"
    return f"Day {(today - WC_START).days + 1} of the 2026 World Cup"


def action_status():
    print(banner("\n  STATUS · wcpa26.com\n  " + "─" * 40))
    print(f"  {DIM}{tournament_day()}{RST}\n")

    meta, e1 = fetch_json("/api/meta.json")
    report, e2 = fetch_json("/api/report.json")
    fixtures, e3 = fetch_json("/api/fixtures.json")

    if meta is None and report is None and fixtures is None:
        print(bad(f"  Could not reach {PROD} — {e1 or e3}"))
        print(warn("  (the site may be down, or you're offline)"))
        return

    # freshness
    gen = (report or {}).get("generated") or (meta or {}).get("generated")
    fresh = rel_time(gen)
    tag = ok if "min" in fresh or "just" in fresh else (warn if "h ago" in fresh else bad)
    print(f"  Site reachable .......... {ok('yes')}")
    print(f"  Model last refreshed .... {tag(fresh)}  {DIM}({gen or '?'}){RST}")
    if report and report.get("runs"):
        print(f"  Last simulation ......... {int(report['runs']):,} runs")

    # champion / favourite
    odds = (report or {}).get("title_odds") or []
    if odds:
        fav = odds[0]
        favpct = ok(f"{fav['p_win'] * 100:.1f}%")
        print(f"  Title favourite ......... {BOLD}{fav['team']}{RST} {favpct}")

    # matches
    if fixtures:
        now = dt.datetime.now(dt.timezone.utc)
        up = fixtures.get("upcoming") or []
        live = [m for m in up if (k := _kick(m.get("kickoff")))
                and 0 <= (now - k).total_seconds() / 60 < LIVE_MIN]
        rec = fixtures.get("record") or {}
        print()
        if live:
            print(f"  {bad('● LIVE NOW')} ({len(live)}):")
            for m in live:
                mins = int((now - _kick(m["kickoff"])).total_seconds() / 60)
                print(f"      {m['home']['team']} v {m['away']['team']}  "
                      f"{bad(str(max(1, mins)) + chr(39))}")
        nxt = next((m for m in sorted(
            (x for x in up if _kick(x.get("kickoff"))),
            key=lambda x: _kick(x["kickoff"])) if _kick(m["kickoff"]) > now), None)
        if nxt:
            delta = _kick(nxt["kickoff"]) - now
            hrs, rem = divmod(int(delta.total_seconds()), 3600)
            print(f"  Next match .............. {nxt['home']['team']} v "
                  f"{nxt['away']['team']}  {CYA}in {hrs}h {rem // 60}m{RST}")
        if rec.get("played"):
            print(f"  Model record ............ {rec['called']}/{rec['played']} "
                  f"called ({rec.get('pct', 0) * 100:.0f}%)")
        else:
            print(f"  Model record ............ {DIM}opens at kickoff{RST}")

    # last local deploy line
    log = os.path.join(ROOT, "deploy_scheduled.log")
    if os.path.exists(log):
        try:
            tail = [ln for ln in open(log, encoding="utf-8", errors="replace")
                    if ln.strip()][-1]
            print(f"\n  {DIM}last deploy log: {tail.strip()[:70]}{RST}")
        except OSError:
            pass


# --------------------------------------------------------------------------- #
#  maintenance actions
# --------------------------------------------------------------------------- #
def action_refresh():
    print(banner("\n  LIVE REFRESH (local) — results+news → retrain → re-sim"))
    print(f"  {DIM}No deploy; updates the local DB + sim only. Use option 3 to push.{RST}")
    rc = engine("refresh")
    print(ok("\n  refresh complete") if rc == 0 else bad(f"\n  refresh exited {rc}"))


def _deploy_cmd():
    # pinned wrangler@4, --yes so a fresh release can never stall on an install prompt
    return ["npx", "--yes", "wrangler@4", "pages", "deploy",
            "--project-name=wcpa", "--branch=main", "--commit-dirty=true"]


def _export_verified():
    """Rebuild ./dist from source via `run.py export`, then verify the exported
    static assets byte-match viz/static — so a stale or truncated CSS/JS can never
    ship (the bug that kept the new profile card unstyled in production)."""
    import filecmp
    if run_cmd([PY, "run.py", "export", "dist"],
               label="export -> ./dist (static + API + cache-bust)") != 0:
        print(bad("  export failed — nothing deployed.")); return False
    for f in ("style.css", "app.js", "index.html"):
        src = os.path.join(ROOT, "viz", "static", f)
        dst = os.path.join(ROOT, "dist", f)
        if not os.path.exists(dst):
            print(bad(f"  dist/{f} missing after export — aborting.")); return False
        if f == "index.html":                       # legit differs (cache-bust stamps) — just require it's whole
            if "</html>" not in open(dst, encoding="utf-8", errors="replace").read():
                print(bad("  dist/index.html looks truncated — aborting.")); return False
        elif not filecmp.cmp(src, dst, shallow=False):
            print(bad(f"  exported dist/{f} != source (stale/truncated) — aborting.")); return False
    print(ok("  export verified — dist static assets match source."))
    return True


def action_deploy(interactive=True):
    print(banner("\n  FULL DEPLOY — refresh live data, re-simulate, rebuild & push"))
    print(f"  {DIM}ingest live + news · retrain · simulate 50k · export · verify · deploy{RST}")
    if interactive and not confirm("  This publishes to the LIVE site. Continue? [y/N]"):
        print(warn("  cancelled")); return
    for args, label in [(["ingest", "live"], "ingest live results"),
                        (["ingest", "news"], "ingest news"),
                        (["train"], "retrain ratings"),
                        (["simulate", "50000"], "simulate 50,000 tournaments")]:
        if run_cmd([PY, "run.py", *args], label=label) != 0:
            print(bad(f"  '{label}' failed — aborting before deploy.")); return
    if not _export_verified():
        return
    print(banner("\n  deploying ./dist to Cloudflare Pages…"))
    rc = run_cmd(_deploy_cmd(), shell=(os.name == "nt"), label="wrangler pages deploy")
    print(ok(f"\n  LIVE — {PROD}  ·  hard-refresh with Ctrl+F5") if rc == 0
          else bad(f"\n  deploy exited {rc}"))


def action_watch():
    print(banner("\n  WATCH MODE — match-day auto-refresh"))
    try:
        raw = input(f"  Refresh every how many minutes? [{CYA}30{RST}] ").strip()
    except (EOFError, KeyboardInterrupt):
        return
    mins = int(raw) if raw.isdigit() and int(raw) > 0 else 30
    deploy = confirm(f"  Also deploy after each refresh? [y/N]")
    print(f"\n  Looping every {mins} min"
          + (" + deploy" if deploy else " (local only)")
          + f". {warn('Ctrl+C to stop.')}\n")
    n = 0
    try:
        while True:
            n += 1
            print(banner(f"  ── cycle {n} · {dt.datetime.now():%H:%M:%S} ──"))
            engine("refresh")
            if deploy:
                run_cmd([PY, "run.py", "export", "dist"], label="export")
                run_cmd(_deploy_cmd(), shell=(os.name == "nt"), label="deploy")
            print(f"  {DIM}sleeping {mins} min…{RST}")
            time.sleep(mins * 60)
    except KeyboardInterrupt:
        print(warn(f"\n  watch stopped after {n} cycle(s)."))


def action_pipeline():
    items = [
        ("health    — DB + data snapshot", ["health"]),
        ("ingest all — results+live+news+xG", ["ingest", "all"]),
        ("train      — Elo + draw + Dixon-Coles + bivpois", ["train"]),
        ("backtest   — leakage-free accuracy (2018+)", ["backtest", "2018"]),
        ("tune       — grid-tune params on held-out RPS", ["tune"]),
        ("calibrate  — fit ensemble temperature", ["calibrate"]),
        ("simulate   — Monte-Carlo (custom run count)", ["simulate"]),
        ("export     — snapshot site to ./dist", ["export", "dist"]),
        ("audit      — security/stability/load gate", ["audit"]),
        ("rankings   — current Elo top-25", ["rankings", "25"]),
        ("groups     — official 2026 draw + tables", ["groups"]),
        ("predict    — single fixture (asks teams)", ["predict"]),
    ]
    while True:
        print(banner("\n  PIPELINE & TOOLS\n  " + "─" * 40))
        for i, (lbl, _) in enumerate(items, 1):
            print(f"   {CYA}{i:>2}{RST}) {lbl}")
        print(f"    {CYA}0{RST}) back")
        try:
            ch = input(f"\n  {BOLD}pipeline ›{RST} ").strip()
        except (EOFError, KeyboardInterrupt):
            return
        if ch in ("0", "", "q"):
            return
        if not ch.isdigit() or not (1 <= int(ch) <= len(items)):
            continue
        lbl, args = items[int(ch) - 1]
        if args == ["simulate"]:
            r = input("  How many runs? [50000] ").strip()
            args = ["simulate", r if r.isdigit() else "50000"]
        elif args == ["predict"]:
            h = input("  Home / Team A: ").strip()
            a = input("  Away / Team B: ").strip()
            if not h or not a:
                continue
            args = ["predict", h, a]
        engine(*args)
        pause()


def action_viz():
    print(banner("\n  LOCAL DASHBOARD — http://localhost:8008  (Ctrl+C to stop)"))
    engine("viz", "8008")


# --------------------------------------------------------------------------- #
#  menu
# --------------------------------------------------------------------------- #
MENU = [
    ("Status & health",        "live site freshness, matches, model record",   action_status),
    ("Full deploy",            "refresh live data + re-sim 50k + rebuild → push", action_deploy),
    ("Watch mode",             "auto-refresh every N min (match-day loop)",     action_watch),
    ("Live refresh",           "pull results+news → retrain → re-sim (local, no deploy)", action_refresh),
    ("Pipeline & tools",       "ingest/train/backtest/tune/simulate/predict…",  action_pipeline),
    ("Open local dashboard",   "run the retro dashboard on :8008",              action_viz),
]


def header():
    print(banner("\n══════════════════════════════════════════════════"))
    print(banner("  WCPA · wcpa26.com maintenance terminal"))
    print(f"  {DIM}{tournament_day()} · {dt.date.today():%a %d %b %Y}{RST}")
    print(banner("══════════════════════════════════════════════════"))


def menu():
    header()
    while True:
        print()
        for i, (name, desc, _) in enumerate(MENU, 1):
            flag = warn("  ⚑ live") if "deploy" in name.lower() else ""
            print(f"   {CYA}{i}{RST}) {BOLD}{name:<22}{RST}{DIM}{desc}{RST}{flag}")
        print(f"   {CYA}0{RST}) {BOLD}Quit{RST}")
        try:
            ch = input(f"\n  {BOLD}wcpa ›{RST} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if ch in ("0", "q", "quit", "exit"):
            break
        if ch.isdigit() and 1 <= int(ch) <= len(MENU):
            try:
                MENU[int(ch) - 1][2]()
            except KeyboardInterrupt:
                print(warn("\n  (cancelled)"))
            if MENU[int(ch) - 1][2] not in (action_pipeline, action_viz, action_watch):
                pause()
        else:
            print(warn("  pick a number from the menu"))
    print(f"  {DIM}bye — {PROD}{RST}")


def main():
    # one-shot subcommands for scripting / Task Scheduler
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else None
    if arg in ("status", "health"):
        action_status()
    elif arg == "refresh":
        action_refresh()
    elif arg == "deploy":
        action_deploy(interactive=False)
    elif arg in (None,):
        menu()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
