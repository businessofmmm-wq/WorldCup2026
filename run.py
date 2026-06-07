#!/usr/bin/env python
"""
World Cup 2026 prediction engine — command line.

    python run.py health                 DB + data snapshot
    python run.py init                   create/upgrade the schema
    python run.py ingest [what]          results | live | news | xg | all
    python run.py train                  recompute Elo + Dixon-Coles ratings
    python run.py predict HOME AWAY      single-fixture prediction (neutral)
    python run.py backtest [year]        leakage-free accuracy backtest (RPS/etc)
    python run.py tune                   grid-tune params on held-out RPS
    python run.py calibrate              fit the ensemble temperature (held-out)
    python run.py simulate [runs]        Monte Carlo the whole tournament
    python run.py groups                 official 2026 final draw + group tables
    python run.py news [team]            latest tagged headlines
    python run.py rankings [n]           current Elo top-N
    python run.py refresh                live+news inflow -> retrain -> resim
    python run.py loop [secs]            run `refresh` forever every N seconds
    python run.py viz [port]             launch the retro dashboard (default :8008)
    python run.py export [dir]           snapshot the dashboard to static files (CDN)
    python run.py loadtest [dir|url]     load-test the static build (spike proof)
    python run.py ogcard                 (re)generate the original OG share card
    python run.py graph [--md|--data]    draw the backend connected graph (VS Code)
    python run.py audit [--no-load]      security + stability + load + hygiene gate
    python run.py simvar [-n N -r R]     variance-reduction benchmark (QMC/antithetic/CV)

`refresh` is the inflow loop: pull the newest results/news, fold them into the
ratings, and re-run the simulation so predictions always reflect latest data.
"""
from __future__ import annotations
import sys
import time
import datetime as dt

# Windows consoles default to cp1252, which can't encode the emoji/arrows the
# engine prints (e.g. the health date-range "->"). Force UTF-8 so the CLI never
# dies on an encode error.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):  # non-reconfigurable stream — fine
    pass

import config
import db
from sources import results as src_results
from sources import sportsdb as src_live
from sources import news as src_news
from sources import statsbomb as src_xg
from models import elo as elo_mod
from models import poisson as poisson_mod
from models.predict import Predictor, fmt
from models.tournament import Tournament


def cmd_health(_args):
    h = db.health()
    print("World Cup 2026 engine — health")
    for k, v in h.items():
        print(f"  {k:<18} {v}")


def cmd_init(_args):
    db.init_schema()
    print("schema ready")


def cmd_ingest(args):
    what = (args[0] if args else "all").lower()
    db.init_schema()
    if what in ("results", "all"):
        print("[results]"); src_results.ingest()
    if what in ("live", "all"):
        print("[live]"); src_live.ingest()
    if what in ("news", "all"):
        print("[news]"); src_news.ingest()
    if what in ("xg", "all"):
        print("[xg]"); src_xg.ingest(limit=(None if what == "xg" else 5))


def cmd_train(_args):
    from models import draw_model
    print("[elo]"); elo_mod.compute()
    print("[draw-model]"); draw_model.fit()
    print("[dixon-coles]"); poisson_mod.fit()
    print("training complete")


def cmd_calibrate(_args):
    from models import tune as tune_mod
    tune_mod.calibrate()


def cmd_predict(args):
    if len(args) < 2:
        print("usage: predict HOME AWAY [--home]"); return
    home, away = args[0], args[1]
    neutral = "--home" not in args
    p = Predictor()
    print(fmt(p.predict(home, away, neutral=neutral, log=True,
                        match_date=dt.date.today())))


def cmd_backtest(args):
    from models import backtest as bt
    year = 2018
    if args and args[0].isdigit():
        year = int(args[0])
    refit = 45
    if "--refit" in args:
        k = args.index("--refit")
        if k + 1 < len(args) and args[k + 1].isdigit():
            refit = int(args[k + 1])
    bt.report(test_start=dt.date(year, 1, 1), refit_days=refit)


def cmd_tune(_args):
    from models import tune as tune_mod
    tune_mod.run()


def cmd_simulate(args):
    runs = int(args[0]) if args and args[0].isdigit() else config.SIM_RUNS
    Tournament().run(runs=runs)


def cmd_groups(_args):
    from models import field_2026
    p = Predictor()
    groups = field_2026.OFFICIAL_GROUPS
    print("Official 2026 final draw (drawn position order; Elo in brackets):\n")
    for g, teams in groups.items():
        print(f"  Group {g}: " + ", ".join(
            f"{t} ({p.elo.get(t, config.ELO_START):.0f})" for t in teams))


def cmd_news(args):
    team = args[0] if args else None
    for row in src_news.recent(20, team=team):
        if team:
            pub, src, title, flags = row
            teams = []
        else:
            pub, src, title, flags, teams = row
        when = pub.strftime("%m-%d %H:%M") if pub else "  ?  "
        fl = f" [{','.join(flags)}]" if flags else ""
        print(f"  {when} {src[:12]:<12} {title[:62]}{fl}")


def cmd_rankings(args):
    n = int(args[0]) if args and args[0].isdigit() else 25
    print(f"Elo top {n} (active, last 4y):")
    for i, (t, e, c) in enumerate(elo_mod.top(n), 1):
        print(f"  {i:>2}. {t:<22}{e:7.1f}  ({c})")


def cmd_refresh(_args):
    print(f"[{dt.datetime.now():%H:%M:%S}] inflow refresh")
    from models import draw_model

    steps = [
        ("live", lambda: src_live.ingest()),
        ("news", lambda: src_news.ingest(verbose=False)),
        ("elo", lambda: elo_mod.compute(verbose=False)),
        ("draw-model", lambda: draw_model.fit(verbose=False)),
        ("dixon-coles", lambda: poisson_mod.fit(verbose=False)),
        ("simulate", lambda: Tournament().run(runs=5000, verbose=True, persist=True)),
    ]

    for name, fn in steps:
        try:
            print(f"[{dt.datetime.now():%H:%M:%S}] {name}...")
            res = fn()
            if isinstance(res, dict):
                print(f"  {name} ok: {res}")
            else:
                print(f"  {name} ok")
        except Exception as exc:
            print(f"  {name} failed: {exc}")


def cmd_loop(args):
    secs = int(args[0]) if args and args[0].isdigit() else 1800
    print(f"inflow loop every {secs}s — Ctrl+C to stop")
    while True:
        try:
            cmd_refresh([])
        except Exception as exc:
            print(f"  refresh error (continuing): {exc}")
        time.sleep(secs)


def cmd_viz(args):
    from viz.server import serve
    port = int(args[0]) if args and args[0].isdigit() else 8008
    serve(port=port)


def cmd_export(args):
    from viz import export as exporter
    out = next((a for a in args if not a.startswith("-")), "dist")
    exporter.build(out, matrix="--no-matrix" not in args)


def cmd_loadtest(args):
    from viz import loadtest
    loadtest.main(args)


def cmd_ogcard(args):
    from viz import ogcard
    ogcard.main(args)


def cmd_graph(args):
    from tools import depgraph
    depgraph.main(args)


def cmd_audit(args):
    from tools import audit
    raise SystemExit(audit.main(args))


def cmd_simvar(args):
    from models import variance
    variance.main(args)


COMMANDS = {
    "health": cmd_health, "init": cmd_init, "ingest": cmd_ingest,
    "train": cmd_train, "predict": cmd_predict, "backtest": cmd_backtest,
    "tune": cmd_tune, "calibrate": cmd_calibrate, "simulate": cmd_simulate,
    "groups": cmd_groups, "news": cmd_news, "rankings": cmd_rankings,
    "refresh": cmd_refresh, "loop": cmd_loop, "viz": cmd_viz,
    "export": cmd_export, "loadtest": cmd_loadtest, "ogcard": cmd_ogcard,
    "graph": cmd_graph, "audit": cmd_audit, "simvar": cmd_simvar,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__)
        return
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
