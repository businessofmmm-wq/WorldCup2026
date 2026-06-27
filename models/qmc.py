"""
Quasi-Monte Carlo + variance-reduction primitives for the tournament simulator.

Pure standard library (the project's tiny-deps ethos — no numpy/scipy). The crude
Monte-Carlo tournament estimates a title probability as a sample mean of an
indicator, so its error falls only as 1/sqrt(N). This module supplies three
classic ways to do better, all behind one tiny `UniformSource` interface so the
simulator can stay oblivious to which is in play:

  * Quasi-Monte Carlo — a **randomised, scrambled Halton** sequence (per-dimension
    random digit permutation + random start). Low-discrepancy points cover the
    unit cube far more evenly than i.i.d. draws, so smooth/low-effective-dimension
    integrands converge closer to 1/N. The randomisation makes it unbiased and
    lets us estimate error from independent scrambles (RQMC).
  * Antithetic variates — pair each draw u with 1-u; negatively-correlated paths
    cancel sampling noise.
  * (Control variates live in the estimator, not here — see models/variance.py.)

Design: the tournament draws one uniform per match-scoreline (the high-leverage
randomness) plus a few *incidental* uniforms (tie-break jitter, shoot-out coin,
slot shuffles). We put the scoreline draws on stable QMC **dimensions** (the
knockout ties on the lowest, best-distributed dimensions) and let the incidental
draws fall back to a plain PRNG — "QMC where it matters, MC elsewhere", a.k.a.
padding the low effective dimension.

    python models/qmc.py        # self-test: QMC vs MC error on a known integral
"""
from __future__ import annotations

import math
import random


# --------------------------------------------------------------------------- #
# Low-discrepancy machinery
# --------------------------------------------------------------------------- #
def first_primes(n: int) -> list[int]:
    """The first *n* primes — the per-dimension bases for a Halton sequence."""
    primes: list[int] = []
    cand = 2
    while len(primes) < n:
        if all(cand % p for p in primes if p * p <= cand):
            primes.append(cand)
        cand += 1
    return primes


class ScrambledHalton:
    """A randomised, scrambled Halton sequence on `dims` dimensions.

    Plain Halton degrades in high dimensions because large-prime bases stay
    correlated for many points. Two cheap, well-known fixes make it a sound RQMC
    rule: a **random permutation of the radical-inverse digits** per dimension
    (Tezuka's random-permutation scrambling) and a **random start** offset. Fresh
    randomisation → an independent, unbiased estimate; average several for error
    bars.
    """

    def __init__(self, dims: int, seed: int | None = None):
        self.dims = dims
        self.bases = first_primes(dims)
        rng = random.Random(seed)
        # one random permutation of {0..b-1} per dimension, applied to every digit
        self.perms = [rng.sample(range(b), b) for b in self.bases]
        self.start = rng.randint(1 << 10, 1 << 16)  # random start (Owen-lite)

    @staticmethod
    def _scrambled_radinv(i: int, base: int, perm: list[int]) -> float:
        f = 1.0
        r = 0.0
        while i > 0:
            f /= base
            r += f * perm[i % base]
            i //= base
        return r

    def point(self, i: int) -> list[float]:
        """The i-th d-dimensional QMC point in [0,1)^d."""
        k = i + self.start
        return [self._scrambled_radinv(k, b, p)
                for b, p in zip(self.bases, self.perms)]


# --------------------------------------------------------------------------- #
# Uniform sources — one interface, three behaviours
# --------------------------------------------------------------------------- #
class UniformSource:
    """Supplies uniforms to one tournament simulation.

    `u(dim)`  — a uniform for a stable, high-leverage decision (QMC dimension).
    `rand()`  — a uniform for an incidental draw (always pseudo-random).
    `shuffle` / `choice` — incidental, pseudo-random helpers.
    """

    def u(self, dim: int) -> float:        # pragma: no cover - interface
        raise NotImplementedError

    def rand(self) -> float:               # pragma: no cover - interface
        raise NotImplementedError

    def shuffle(self, seq) -> None:
        # Fisher-Yates off our own rand() so every source is self-contained.
        for i in range(len(seq) - 1, 0, -1):
            j = int(self.rand() * (i + 1))
            j = i if j > i else j
            seq[i], seq[j] = seq[j], seq[i]


class PRNGSource(UniformSource):
    """Plain pseudo-random draws — reproduces the original crude-MC behaviour.

    With `antithetic=True` it returns 1-u on alternate constructions (the caller
    flips `mirror` per paired simulation), giving antithetic variates.
    """

    def __init__(self, rng: random.Random, mirror: bool = False):
        self.rng = rng
        self.mirror = mirror

    def u(self, dim: int) -> float:
        x = self.rng.random()
        return 1.0 - x if self.mirror else x

    def rand(self) -> float:
        # Incidental draws are never mirrored (they are low-leverage and mirroring
        # discrete coins/shuffles would not help).
        return self.rng.random()


class QMCSource(UniformSource):
    """A scrambled-Halton point drives the high-leverage scoreline dimensions;
    a PRNG covers incidental draws."""

    def __init__(self, point: list[float], rng: random.Random):
        self._pt = point
        self.rng = rng

    def u(self, dim: int) -> float:
        if 0 <= dim < len(self._pt):
            return self._pt[dim]
        return self.rng.random()           # ran past the allocated dimensions

    def rand(self) -> float:
        return self.rng.random()


# --------------------------------------------------------------------------- #
# Self-test — prove the sampler actually lowers error
# --------------------------------------------------------------------------- #
def _test_integral(dims: int, n: int, reps: int = 24) -> tuple[float, float]:
    """RMSE of MC vs scrambled-Halton estimating ∫_[0,1]^d ∏|4x_k-2| dx = 1.

    A standard QMC test integrand (mean exactly 1). Returns (rmse_mc, rmse_qmc).
    """
    def f(x):
        p = 1.0
        for v in x:
            p *= abs(4.0 * v - 2.0)
        return p

    se_mc = se_qmc = 0.0
    for r in range(reps):
        rng = random.Random(1000 + r)
        # crude Monte Carlo
        acc = sum(f([rng.random() for _ in range(dims)]) for _ in range(n))
        se_mc += (acc / n - 1.0) ** 2
        # randomised QMC (fresh scramble per replication)
        hal = ScrambledHalton(dims, seed=5000 + r)
        acc = sum(f(hal.point(i)) for i in range(n))
        se_qmc += (acc / n - 1.0) ** 2
    return math.sqrt(se_mc / reps), math.sqrt(se_qmc / reps)


def _selftest() -> None:
    print("Scrambled-Halton RQMC self-test")
    print("  integrand ∏|4x-2| over [0,1]^d, true mean = 1.0\n")
    print(f"  {'dims':>4} {'N':>7} {'RMSE MC':>11} {'RMSE QMC':>11} {'var-reduction':>14}")
    for dims in (2, 6, 16, 32):
        n = 4096
        rmse_mc, rmse_qmc = _test_integral(dims, n)
        vrf = (rmse_mc / rmse_qmc) ** 2 if rmse_qmc else float("inf")
        print(f"  {dims:>4} {n:>7} {rmse_mc:>11.5f} {rmse_qmc:>11.5f} {vrf:>12.1f}x")
    print("\n  (variance-reduction = (RMSE_MC / RMSE_QMC)^2; >1 means QMC wins)")


if __name__ == "__main__":
    import sys
    try:                                    # Windows cp1252 can't encode ∏ / ×
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    _selftest()
