"""
Backtest agent — one command to grade the prediction model two ways.

  1. HISTORICAL (leakage-free walk-forward over held-out internationals): reuses
     models.backtest.report() — RPS / log-loss / Brier / accuracy for the Elo,
     goals, and ensemble streams vs the no-skill baselines.
  2. LIVE scorecard: grades the model's OWN frozen pre-kickoff calls (the
     `predictions` table) against the actual results of this tournament so far —
     the only honest test of the *current* model (incl. the form overlay) on
     WC2026. Reports RPS/Brier/log-loss/accuracy, skill vs a uniform 1/3 baseline,
     and a favourite-calibration table.

Usage:
    python -m tools.backtest_agent                 # both
    python -m tools.backtest_agent --hist-only
    python -m tools.backtest_agent --live-only
    python -m tools.backtest_agent --year 2022 --refit 45
"""
from __future__ import annotations
import argparse
import datetime as dt
import math

import config
from db import connect

_OUT = {"home": (1, 0, 0), "draw": (0, 1, 0), "away": (0, 0, 1)}


def _outcome(hs: int, as_: int) -> str:
    return "home" if hs > as_ else "away" if hs < as_ else "draw"


def rps_1x2(p, outcome) -> float:
    a = _OUT[outcome]
    cp = (p[0], p[0] + p[1]); ca = (a[0], a[0] + a[1])
    return 0.5 * sum((x - y) ** 2 for x, y in zip(cp, ca))


def brier(p, outcome) -> float:
    a = _OUT[outcome]
    return sum((pi - ai) ** 2 for pi, ai in zip(p, a))


def logloss(p, outcome) -> float:
    idx = {"home": 0, "draw": 1, "away": 2}[outcome]
    return -math.log(max(p[idx], 1e-12))


def argmax_outcome(p) -> str:
    return ("home", "draw", "away")[max(range(3), key=lambda i: p[i])]


# --------------------------------------------------------------------------- #
def historical(year: int | None, refit: int) -> None:
    print("\n=== HISTORICAL backtest (leakage-free walk-forward) ===")
    try:
        from models import backtest as bt
        start = dt.date(year, 1, 1) if year else None
        bt.report(test_start=start, refit_days=refit)   # prints its own table
    except Exception as exc:
        print(f"  historical backtest unavailable: {exc}")


def live_scorecard(window_start: str | None = None) -> dict:
    start = window_start or getattr(config, "FORM_WINDOW_START", "2026-06-01")
    print(f"\n=== LIVE scorecard — model's frozen calls vs results (since {start}) ===")
    try:
        with connect() as conn:
            preds = conn.execute(
                """
                SELECT home_team, away_team, match_date, p_home, p_draw, p_away, created_at
                FROM predictions
                WHERE match_date >= %s
                ORDER BY created_at
                """, (start,)).fetchall()
            results = conn.execute(
                """
                SELECT home_team, away_team, match_date, home_score, away_score
                FROM matches
                WHERE status='finished' AND home_score IS NOT NULL AND away_score IS NOT NULL
                  AND tournament ILIKE %s AND match_date >= %s
                """, ("%World Cup%", start)).fetchall()
    except Exception as exc:
        print(f"  live scorecard unavailable (DB): {exc}")
        return {}

    # earliest (frozen, pre-kickoff) prediction per fixture
    frozen: dict = {}
    for h, a, d, ph, pd, pa, _ in preds:
        frozen.setdefault((h, a, str(d)), (ph, pd, pa))

    rows, miss = [], 0
    for h, a, d, hs, as_ in results:
        p = frozen.get((h, a, str(d)))
        if not p or p[0] is None:
            miss += 1; continue
        p = (float(p[0]), float(p[1]), float(p[2]))
        oc = _outcome(hs, as_)
        rows.append((h, a, p, oc, hs, as_))

    n = len(rows)
    if not n:
        print(f"  no graded fixtures yet (results={len(results)}, matched preds=0, "
              f"unmatched={miss}). Predictions are logged at export — deploy once "
              f"during a match window to start the scorecard.")
        return {"n": 0}

    rps = sum(rps_1x2(r[2], r[3]) for r in rows) / n
    br = sum(brier(r[2], r[3]) for r in rows) / n
    ll = sum(logloss(r[2], r[3]) for r in rows) / n
    acc = sum(1 for r in rows if argmax_outcome(r[2]) == r[3]) / n
    base_rps = sum(rps_1x2((1/3, 1/3, 1/3), r[3]) for r in rows) / n
    skill = (base_rps - rps) / base_rps if base_rps else 0.0

    print(f"  graded fixtures : {n}  (unmatched results: {miss})")
    print(f"  RPS             : {rps:.4f}   (uniform baseline {base_rps:.4f} · skill {skill:+.1%})")
    print(f"  log-loss        : {ll:.4f}")
    print(f"  Brier           : {br:.4f}")
    print(f"  accuracy (argmax): {acc:.1%}")

    # favourite calibration: bin by the model's max prob, show observed hit-rate
    bins = [(0.34, 0.45), (0.45, 0.55), (0.55, 0.70), (0.70, 1.01)]
    print("  favourite calibration (predicted band -> observed hit-rate):")
    for lo, hi in bins:
        sub = [r for r in rows if lo <= max(r[2]) < hi]
        if not sub:
            continue
        hit = sum(1 for r in sub if argmax_outcome(r[2]) == r[3]) / len(sub)
        avg = sum(max(r[2]) for r in sub) / len(sub)
        print(f"    {lo:.2f}-{hi:.2f}: n={len(sub):>2}  predicted~{avg:.0%}  actual {hit:.0%}")

    worst = sorted(rows, key=lambda r: rps_1x2(r[2], r[3]), reverse=True)[:5]
    print("  biggest misses:")
    for h, a, p, oc, hs, as_ in worst:
        print(f"    {h} {hs}-{as_} {a}  (model: H{p[0]:.0%}/D{p[1]:.0%}/A{p[2]:.0%}, {oc} happened)")
    return {"n": n, "rps": rps, "log_loss": ll, "brier": br, "acc": acc,
            "baseline_rps": base_rps, "skill": skill}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WCPA backtest agent")
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--refit", type=int, default=45)
    ap.add_argument("--hist-only", action="store_true")
    ap.add_argument("--live-only", action="store_true")
    args = ap.parse_args(argv)
    print("WCPA — backtest agent")
    if not args.live_only:
        historical(args.year, args.refit)
    if not args.hist_only:
        live_scorecard()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
