"""
Pure-Python self-tests for the method-upgrade work (no DB, no numpy).

Each upgrade is a no-op at its identity parameter and must demonstrably move its
target metric on synthetic data. These verify the *mechanics*; the *real*
held-out gain is confirmed with `python run.py backtest` against the historical DB.

Run:  python tools/test_upgrades.py
"""
from __future__ import annotations
import os
import sys
import random

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models import metrics       # noqa: E402
from models import calibrate     # noqa: E402
from models import pirating      # noqa: E402


def _sharpen(p, gamma):
    q = [max(x, 1e-12) ** gamma for x in p]
    s = sum(q)
    return tuple(x / s for x in q)


def _gen_overconfident(n=4000, seed=7, gamma=1.6):
    rnd = random.Random(seed)
    rows = []
    for _ in range(n):
        a, b, c = rnd.random() + 0.25, rnd.random() + 0.25, rnd.random() + 0.25
        s = a + b + c
        true = (a / s, b / s, c / s)
        r = rnd.random()
        o = 0 if r < true[0] else (1 if r < true[0] + true[1] else 2)
        rows.append((_sharpen(true, gamma), o))
    return rows


def test_phase1_vector_temperature():
    rows = _gen_overconfident()
    ece0 = metrics.reliability_error(rows)
    ll0 = metrics.score_stream(rows)["log_loss"]
    temps = calibrate.fit_vector_temperature(rows)
    recal = [(calibrate.apply_vector_temperature(p, temps), o) for p, o in rows]
    ece1 = metrics.reliability_error(recal)
    ll1 = metrics.score_stream(recal)["log_loss"]
    assert ece1 < ece0, f"ECE not reduced: {ece0:.4f} -> {ece1:.4f}"
    assert ll1 <= ll0 + 1e-9, f"log-loss not reduced: {ll0:.4f} -> {ll1:.4f}"
    p = (0.5, 0.3, 0.2)
    assert max(abs(a - b) for a, b in zip(calibrate.apply_vector_temperature(p, (1, 1, 1)), p)) < 1e-9
    print(f"  [P1] vector-temp OK   ECE {ece0:.4f}->{ece1:.4f}  "
          f"LL {ll0:.4f}->{ll1:.4f}  T={tuple(round(t, 2) for t in temps)}")


def test_phase2_shrinkage():
    rows = _gen_overconfident(gamma=1.8)
    brier0 = metrics.score_stream(rows)["brier"]
    prior = calibrate.base_rate(rows)
    lam = calibrate.fit_shrinkage(rows, prior)
    recal = [(calibrate.apply_shrinkage(p, lam, prior), o) for p, o in rows]
    brier1 = metrics.score_stream(recal)["brier"]
    assert lam > 0.0, "expected non-zero shrinkage on over-confident data"
    assert brier1 < brier0, f"Brier not reduced: {brier0:.4f} -> {brier1:.4f}"
    p = (0.5, 0.3, 0.2)
    assert max(abs(a - b) for a, b in zip(calibrate.apply_shrinkage(p, 0.0, prior), p)) < 1e-9
    out = calibrate.apply_shrinkage(p, lam, prior)
    assert abs(sum(out) - 1.0) < 1e-9 and all(x >= 0 for x in out)
    print(f"  [P2] shrinkage OK     Brier {brier0:.4f}->{brier1:.4f}  "
          f"lam={lam:.2f}  prior={tuple(round(x, 2) for x in prior)}")


def test_phase3_pirating():
    pr = pirating.PiRatings()
    for _ in range(50):
        pr.update("A", "B", 2, 0, neutral=True)   # A consistently beats B by 2
    gd = pr.expected_gd("A", "B", neutral=True)
    assert gd > 0, f"A should out-rate B, gd={gd}"
    p = pirating.predict_1x2(pr, "A", "B", neutral=True)
    assert p["p_home"] > p["p_away"], p
    assert abs(sum(p.values()) - 1.0) < 1e-9
    sym = pirating.gd_to_1x2(0.0)
    assert abs(sym["p_home"] - sym["p_away"]) < 1e-9, "draw band must be symmetric at gd=0"
    assert pirating.gd_to_1x2(1.0)["p_home"] > pirating.gd_to_1x2(0.0)["p_home"]
    print(f"  [P3] pi-ratings OK    A-B gd={gd:.2f}  "
          f"1X2={tuple(round(p[k], 3) for k in ('p_home', 'p_draw', 'p_away'))}")


TESTS = [test_phase1_vector_temperature, test_phase2_shrinkage, test_phase3_pirating]


if __name__ == "__main__":
    for t in TESTS:
        t()
    print(f"ALL {len(TESTS)} UPGRADE TEST(S) PASSED")
