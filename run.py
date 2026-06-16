#!/usr/bin/env python
"""
World Cup 2026 prediction engine — command line.

    python run.py health                 DB + data snapshot
    python run.py init                   create/upgrade the schema
    python run.py ingest [what]          results | live | news | xg | all
    python run.py train                  recompute Elo + Dixon-Coles ratings
    python run.py predict HOME AWAY      single-fixture prediction (neutral)
    python run.py backtest [year]        leakage-free accuracy backtest (RPS/etc)
    python run.py backtest [year] --compare   bivariate-Poisson vs Dixon-Coles
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
    python run.py cv <clip> --home H --away A --date D   Quantum Tactics CV pass (local, CC clip)

`refresh` is the inflow loop: pull the newest results/news, fold them into the
ratings, and re-run the simulation so predictions always reflect latest data.
"""
from __future__ import annotations
import argparse
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
from sources import footballdata as src_live
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
    what = args.what.lower()
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
    from models import bivpoisson as bivpois
    print("[elo]"); elo_mod.compute()
    print("[draw-model]"); draw_model.fit()
    print("[dixon-coles]"); dc = poisson_mod.fit()
    # Bivariate Poisson reuses the just-fit DC marginals and adds the shared
    # covariance lambda3, so the attack/defence MLE is not paid for twice. Always
    # fit both BP variants (cheap 1-D fits) to keep them warm.
    print("[bivariate-poisson]"); bivpois.fit(base=dc)
    print("[bivariate-poisson-diagonal]"); bivpois.fit_diagonal(base=dc)
    print("training complete")


def cmd_calibrate(_args):
    from models import tune as tune_mod
    tune_mod.calibrate()


def cmd_predict(args):
    p = Predictor()
    print(fmt(p.predict(args.home, args.away, neutral=not args.home_field, log=True,
                        match_date=dt.date.today())))


def cmd_backtest(args):
    from models import backtest as bt
    if args.compare:   # bivariate-Poisson vs Dixon-Coles head-to-head
        bt.compare(test_start=dt.date(args.year, 1, 1), refit_days=args.refit)
    else:
        bt.report(test_start=dt.date(args.year, 1, 1), refit_days=args.refit)


def cmd_tune(_args):
    from models import tune as tune_mod
    tune_mod.run()


def cmd_simulate(args):
    Tournament().run(runs=args.runs)


def cmd_groups(_args):
    from models import field_2026
    p = Predictor()
    groups = field_2026.OFFICIAL_GROUPS
    print("Official 2026 final draw (drawn position order; Elo in brackets):\n")
    for g, teams in groups.items():
        print(f"  Group {g}: " + ", ".join(
            f"{t} ({p.elo.get(t, config.ELO_START):.0f})" for t in teams))


def cmd_news(args):
    team = args.team
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
    n = args.n
    print(f"Elo top {n} (active, last 4y):")
    for i, (t, e, c) in enumerate(elo_mod.top(n), 1):
        print(f"  {i:>2}. {t:<22}{e:7.1f}  ({c})")


def cmd_refresh(_args):
    print(f"[{dt.datetime.now():%H:%M:%S}] inflow refresh")
    from models import draw_model
    from models import bivpoisson as bivpois

    def _fit_goals():
        # Fit DC once; both BP variants ride the same marginals — no double fit.
        dc = poisson_mod.fit(verbose=False)
        bivpois.fit(base=dc)
        bivpois.fit_diagonal(base=dc)

    steps = [
        ("live", lambda: src_live.ingest()),
        ("news", lambda: src_news.ingest(verbose=False)),
        ("elo", lambda: elo_mod.compute(verbose=False)),
        ("draw-model", lambda: draw_model.fit(verbose=False)),
        ("dixon-coles + bivpois", _fit_goals),
        ("simulate", lambda: Tournament().run(
            runs=config.REFRESH_RUNS, method=config.REFRESH_METHOD,
            verbose=True, persist=True)),
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
    print(f"inflow loop every {args.secs}s — Ctrl+C to stop")
    while True:
        try:
            cmd_refresh(args)
        except Exception as exc:
            print(f"  refresh error (continuing): {exc}")
        time.sleep(args.secs)


def cmd_viz(args):
    from viz.server import serve
    serve(port=args.port)


def cmd_export(args):
    from viz import export as exporter
    exporter.build(args.dir, matrix=not args.no_matrix)


def cmd_loadtest(args):
    from viz import loadtest
    loadtest.main([args.target])


def cmd_ogcard(args):
    from viz import ogcard
    ogcard.main([])


def cmd_graph(args):
    from tools import depgraph
    depgraph.main([])


def cmd_audit(args):
    from tools import audit
    raise SystemExit(audit.main(args))


def cmd_simvar(args):
    from models import variance
    variance_args = []
    if args.num is not None:
        variance_args.extend(["-n", str(args.num)])
    if args.runs is not None:
        variance_args.extend(["-r", str(args.runs)])
    variance.main(variance_args)


def cmd_cv(args):
    # Lazy import: tools.cv_tactics pulls in OpenCV/Ultralytics only when actually run,
    # so the heavy CV stack never loads for any other command (or any serving path).
    from tools import cv_tactics
    raise SystemExit(cv_tactics.main([
        args.clip,
        "--home",
        args.home,
        "--away",
        args.away,
        "--date",
        args.date,
    ]))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="World Cup 2026 prediction engine — command line.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")
    subparsers.required = True

    subparsers.add_parser("health", help="DB + data snapshot").set_defaults(func=cmd_health)
    subparsers.add_parser("init", help="create/upgrade the schema").set_defaults(func=cmd_init)

    ingest = subparsers.add_parser("ingest", help="results | live | news | xg | all")
    ingest.add_argument("what", nargs="?", default="all",
                        choices=["results", "live", "news", "xg", "all"])
    ingest.set_defaults(func=cmd_ingest)

    subparsers.add_parser("train", help="recompute Elo + Dixon-Coles ratings").set_defaults(func=cmd_train)

    predict = subparsers.add_parser("predict", help="single-fixture prediction")
    predict.add_argument("home")
    predict.add_argument("away")
    predict.add_argument("--home", dest="home_field", action="store_true",
                         help="treat the first team as the home side")
    predict.set_defaults(func=cmd_predict)

    backtest = subparsers.add_parser("backtest", help="leakage-free accuracy backtest")
    backtest.add_argument("year", nargs="?", type=int, default=2018)
    backtest.add_argument("--compare", action="store_true",
                          help="compare bivariate-Poisson vs Dixon-Coles")
    backtest.add_argument("--refit", type=int, default=45,
                          help="refit interval in days")
    backtest.set_defaults(func=cmd_backtest)

    subparsers.add_parser("tune", help="grid-tune params on held-out RPS").set_defaults(func=cmd_tune)
    subparsers.add_parser("calibrate", help="fit the ensemble temperature").set_defaults(func=cmd_calibrate)

    simulate = subparsers.add_parser("simulate", help="Monte Carlo the whole tournament")
    simulate.add_argument("runs", nargs="?", type=int, default=config.SIM_RUNS)
    simulate.set_defaults(func=cmd_simulate)

    subparsers.add_parser("groups", help="official 2026 final draw + group tables").set_defaults(func=cmd_groups)

    news = subparsers.add_parser("news", help="latest tagged headlines")
    news.add_argument("team", nargs="?")
    news.set_defaults(func=cmd_news)

    rankings = subparsers.add_parser("rankings", help="current Elo top-N")
    rankings.add_argument("n", nargs="?", type=int, default=25)
    rankings.set_defaults(func=cmd_rankings)

    subparsers.add_parser("refresh", help="live+news inflow -> retrain -> resim").set_defaults(func=cmd_refresh)

    loop = subparsers.add_parser("loop", help="run refresh forever every N seconds")
    loop.add_argument("secs", nargs="?", type=int, default=1800)
    loop.set_defaults(func=cmd_loop)

    viz = subparsers.add_parser("viz", help="launch the retro dashboard")
    viz.add_argument("port", nargs="?", type=int, default=8008)
    viz.set_defaults(func=cmd_viz)

    export = subparsers.add_parser("export", help="snapshot the dashboard to static files")
    export.add_argument("dir", nargs="?", default="dist")
    export.add_argument("--no-matrix", action="store_true", help="skip matrix export")
    export.set_defaults(func=cmd_export)

    loadtest = subparsers.add_parser("loadtest", help="load-test the static build")
    loadtest.add_argument("target")
    loadtest.set_defaults(func=cmd_loadtest)

    subparsers.add_parser("ogcard", help="(re)generate the original OG share card").set_defaults(func=cmd_ogcard)
    subparsers.add_parser("graph", help="draw the backend connected graph").set_defaults(func=cmd_graph)
    subparsers.add_parser("audit", help="security + stability + load + hygiene gate").set_defaults(func=cmd_audit)

    simvar = subparsers.add_parser("simvar", help="variance-reduction benchmark")
    simvar.add_argument("-n", "--num", type=int, default=None,
                        help="sample size for variance benchmark")
    simvar.add_argument("-r", "--runs", type=int, default=None,
                        help="simulation run count for benchmark")
    simvar.set_defaults(func=cmd_simvar)

    cv = subparsers.add_parser("cv", help="Quantum Tactics CV pass")
    cv.add_argument("clip")
    cv.add_argument("--home", required=True)
    cv.add_argument("--away", required=True)
    cv.add_argument("--date", required=True)
    cv.set_defaults(func=cmd_cv)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted")
    except Exception as exc:
        print(f"ERROR: {exc}")
        raise


if __name__ == "__main__":
    main()
