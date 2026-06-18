"""
Recalibration phase — refit the model to the tournament as it actually unfolds.

Two layers:
  1. LIVE temperature recalibration (the new bit): re-derives each frozen
     pre-kickoff prediction's UN-tempered ensemble from its stored components
     (predictions.detail), then grid-searches the calibration temperature T that
     minimises RPS / log-loss on the WC2026 games played so far. Pure arithmetic
     on stored predictions — no engine refit, no leakage (calls were frozen before
     kickoff). Small sample, so it reports rather than over-fits, and blends the
     live-optimal T with the historical-optimal T before applying.
  2. HISTORICAL recalibration (--full): runs the existing held-out tuners
     (models.tune.calibrate / .run) that write data/tuned_params.json.

Usage:
    python -m tools.recalibrate              # report live vs historical T
    python -m tools.recalibrate --apply      # blend + write ENSEMBLE_TEMPERATURE
    python -m tools.recalibrate --full        # also run the historical tuners first
"""
from __future__ import annotations
import argparse
import json
import os
import datetime as dt

import config
from db import connect

_OUT = {"home": (1, 0, 0), "draw": (0, 1, 0), "away": (0, 0, 1)}


def _temper(p, t):
    if t == 1.0:
        s = sum(p) or 1.0
        return tuple(x / s for x in p)
    q = [max(x, 1e-9) ** (1.0 / t) for x in p]
    s = sum(q) or 1.0
    return tuple(x / s for x in q)


def _rps(p, oc):
    a = _OUT[oc]
    cp = (p[0], p[0] + p[1]); ca = (a[0], a[0] + a[1])
    return 0.5 * sum((x - y) ** 2 for x, y in zip(cp, ca))


def _ll(p, oc):
    import math
    i = {"home": 0, "draw": 1, "away": 2}[oc]
    return -math.log(max(p[i], 1e-12))


def _outcome(hs, a):
    return "home" if hs > a else "away" if hs < a else "draw"


def _load_live(window_start: str):
    """Return [(p0_untempered, outcome)] from frozen calls + results."""
    with connect() as conn:
        preds = conn.execute(
            """SELECT home_team, away_team, match_date, p_home, p_draw, p_away, detail, created_at
               FROM predictions WHERE match_date >= %s ORDER BY created_at""",
            (window_start,)).fetchall()
        results = conn.execute(
            """SELECT home_team, away_team, match_date, home_score, away_score
               FROM matches WHERE status='finished' AND home_score IS NOT NULL
                 AND tournament ILIKE %s AND match_date >= %s""",
            ("%World Cup%", window_start)).fetchall()
    we, wd = config.ENSEMBLE_ELO_WEIGHT, config.ENSEMBLE_DC_WEIGHT
    wsum = we + wd
    frozen = {}
    for h, a, d, ph, pd, pa, detail, _ in preds:
        key = (h, a, str(d))
        if key in frozen:
            continue                       # earliest only (pre-kickoff freeze)
        det = detail if isinstance(detail, dict) else (json.loads(detail) if detail else {})
        e, g = det.get("elo"), det.get("goals")
        if e and g and all(k in e for k in ("p_home", "p_draw", "p_away")):
            p0 = ((we * e["p_home"] + wd * g["p_home"]) / wsum,
                  (we * e["p_draw"] + wd * g["p_draw"]) / wsum,
                  (we * e["p_away"] + wd * g["p_away"]) / wsum)
        else:
            p0 = (ph, pd, pa)              # fall back to stored (already tempered)
        frozen[key] = p0
    out = []
    for h, a, d, hs, as_ in results:
        p0 = frozen.get((h, a, str(d)))
        if p0:
            out.append((p0, _outcome(hs, as_)))
    return out


def live_temperature(window_start: str | None = None):
    start = window_start or getattr(config, "FORM_WINDOW_START", "2026-06-01")
    try:
        data = _load_live(start)
    except Exception as exc:
        print(f"  live recalibration unavailable (DB): {exc}")
        return None
    n = len(data)
    if n < 8:
        print(f"  only {n} graded games since {start} — too few to recalibrate live "
              f"(need ~8+). Reporting only.")
    if not data:
        return None
    grid = [round(0.6 + 0.05 * i, 2) for i in range(0, 25)]   # 0.60 .. 1.80
    def score(t):
        return (sum(_rps(_temper(p, t), oc) for p, oc in data) / n,
                sum(_ll(_temper(p, t), oc) for p, oc in data) / n)
    rows = [(t, *score(t)) for t in grid]
    best_t, best_rps, best_ll = min(rows, key=lambda r: r[1])
    cur_t = config.ENSEMBLE_TEMPERATURE
    cur_rps, cur_ll = score(cur_t)
    one_rps, one_ll = score(1.0)
    print(f"\n=== LIVE temperature recalibration ({n} games since {start}) ===")
    print(f"  T=1.00          : RPS {one_rps:.4f}  LogLoss {one_ll:.4f}")
    print(f"  current T={cur_t:<4}: RPS {cur_rps:.4f}  LogLoss {cur_ll:.4f}")
    print(f"  live-best T={best_t:<4}: RPS {best_rps:.4f}  LogLoss {best_ll:.4f}")
    return {"n": n, "best_t": best_t, "best_rps": best_rps, "cur_t": cur_t, "cur_rps": cur_rps}


def _merge_tuned(updates: dict):
    path = os.path.join(config.DATA_DIR, "tuned_params.json")
    try:
        params = json.load(open(path, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        params = {}
    params.update(updates)
    json.dump(params, open(path, "w", encoding="utf-8"), indent=1)
    print(f"  wrote {updates} -> {path}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="WCPA recalibration phase")
    ap.add_argument("--apply", action="store_true", help="write the blended temperature to tuned_params.json")
    ap.add_argument("--full", action="store_true", help="also run the historical tuners first")
    ap.add_argument("--blend", type=float, default=0.5, help="weight on the LIVE T vs historical (0..1)")
    args = ap.parse_args(argv)
    print("WCPA — recalibration phase")

    if args.full:
        try:
            from models import tune as tune_mod
            print("\n=== HISTORICAL tune + calibrate (held-out) ===")
            tune_mod.run(); tune_mod.calibrate()
        except Exception as exc:
            print(f"  historical tuners failed: {exc}")

    res = live_temperature()
    if args.apply and res and res["n"] >= 8:
        hist_t = config.ENSEMBLE_TEMPERATURE
        # conservative blend of live-optimal and historical temperature
        blended = round(args.blend * res["best_t"] + (1 - args.blend) * hist_t, 3)
        # only apply if it beats the current setting on the live slice
        if res["best_rps"] < res["cur_rps"] - 1e-4:
            _merge_tuned({"ENSEMBLE_TEMPERATURE": blended})
            print(f"  applied blended T={blended} (live {res['best_t']} ⊕ hist {hist_t}). "
                  f"Retrain/redeploy to use it.")
        else:
            print("  live slice doesn't beat current T — leaving it unchanged.")
    elif args.apply:
        print("  not applying: too few live games.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
