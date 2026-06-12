"""
World Cup 2026 Monte Carlo tournament simulator.

2026 format: 48 teams in 12 groups (A-L) of four. Group winners + runners-up
(24) plus the 8 best third-placed teams advance to a Round of 32, then a
single-elimination bracket R32 -> R16 -> QF -> SF -> Final.

Each simulated tournament:
  - draws 12 groups from four Elo-based pots (or uses a supplied draw),
  - plays every group match by SAMPLING a scoreline from the Dixon-Coles grid
    (so points, goal difference and goals-for tiebreakers are consistent),
  - ranks groups, selects the 8 best thirds,
  - runs the knockout bracket (draws decided by relative win odds = the
    penalty-shootout proxy).

Run many times to get advancement / title probabilities. Pure Python; the
inner loop samples from the cached scoreline grid so it stays fast.
"""
from __future__ import annotations
import json
import os
import random
import datetime as dt
from collections import defaultdict

import config
from db import connect
from models.predict import Predictor
from models import field_2026
from models import qmc


GROUP_LETTERS = [chr(ord("A") + i) for i in range(12)]

# The six round-robin pairings of a four-team group, in a fixed order so each
# can be given a stable QMC dimension.
PAIRS = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]

# Knockout ties in *descending leverage* — the final decides the champion, so it
# gets the lowest (best-distributed) QMC dimension, then the semis, quarters and
# round-of-16. The round-of-32 and the 72 group matches follow. Concentrating QMC
# on the low-leverage... er, *high*-leverage low dimensions is what makes it pay
# off on a problem whose nominal dimension (~103) is far above QMC's sweet spot.
_KO_BY_LEVERAGE = [104, 101, 102, 97, 98, 99, 100, 96, 95, 94, 93, 92, 91, 90, 89]


def make_pots(field: list[str], elo: dict) -> list[list[str]]:
    """Sort the field by Elo and split into four pots of 12 (hosts forced to pot 1)."""
    ranked = sorted(field, key=lambda t: elo.get(t, config.ELO_START), reverse=True)
    # hosts are conventionally pot 1 — pull them to the front
    hosts = [t for t in field_2026.HOSTS if t in field]
    ranked = hosts + [t for t in ranked if t not in hosts]
    return [ranked[i * 12:(i + 1) * 12] for i in range(4)]


def draw_groups(pots: list[list[str]], rng: random.Random) -> dict[str, list[str]]:
    """One team per pot per group, with a light confederation-spreading rule."""
    pots = [p[:] for p in pots]
    for p in pots:
        rng.shuffle(p)
    groups: dict[str, list[str]] = {g: [] for g in GROUP_LETTERS}
    confeds: dict[str, set] = {g: set() for g in GROUP_LETTERS}
    for pot in pots:
        order = GROUP_LETTERS[:]
        rng.shuffle(order)
        for team in pot:
            conf = field_2026.CONFED_OF.get(team, "?")
            # prefer a group without this confederation (UEFA may double up)
            placed = False
            for g in sorted(order, key=lambda g: len(groups[g])):
                if len(groups[g]) >= 4:
                    continue
                if conf in confeds[g] and conf != "UEFA":
                    continue
                groups[g].append(team)
                confeds[g].add(conf)
                placed = True
                break
            if not placed:  # fallback: first group with room
                for g in order:
                    if len(groups[g]) < 4:
                        groups[g].append(team)
                        confeds[g].add(conf)
                        break
    return groups


WC_START_2026 = dt.date(2026, 6, 11)


def _load_played() -> tuple[dict, dict]:
    """Real finished WC-2026 results (+ shootout winners), keyed by team pair.

    Locked into every simulated tournament so the published odds *condition on
    what has actually happened* — the sim only randomises the future. Without
    this, a side that already banked 6 points would still see its group
    re-randomised 50,000 times. Empty dicts (e.g. pre-tournament, or no DB)
    reproduce the unconditioned sim exactly.
    """
    results: dict = {}
    shootouts: dict = {}
    try:
        with connect() as conn:
            rows = conn.execute(
                "SELECT home_team, away_team, home_score, away_score FROM matches "
                "WHERE tournament='FIFA World Cup' AND match_date >= %s "
                "AND home_score IS NOT NULL AND away_score IS NOT NULL",
                (WC_START_2026,)).fetchall()
            results = {(h, a): (hs, as_) for h, a, hs, as_ in rows}
            srows = conn.execute(
                "SELECT s.home_team, s.away_team, s.winner FROM shootouts s "
                "JOIN matches m ON m.match_date = s.match_date "
                "  AND m.home_team = s.home_team AND m.away_team = s.away_team "
                "WHERE m.tournament='FIFA World Cup' AND m.match_date >= %s "
                "  AND s.winner IS NOT NULL",
                (WC_START_2026,)).fetchall()
            shootouts = {(h, a): w for h, a, w in srows}
    except Exception:
        pass                                     # no DB / no table → uncondition
    return results, shootouts


class Tournament:
    def __init__(self, predictor: Predictor | None = None, seed: int | None = None):
        self.pred = predictor or Predictor()
        self.elo = self.pred.elo
        self.rng = random.Random(seed)
        # Played-match conditioning (real scores override sampling).
        self.real_results, self.real_shootouts = _load_played()
        # cache scoreline grids per ordered pair (neutral) — big speed win
        self._grid_cache: dict[tuple, tuple] = {}
        # Stable QMC dimension for every match decision (knockouts first, on the
        # best-distributed low dimensions; group matches last).
        self._dim: dict = {}
        d = 0
        for m in _KO_BY_LEVERAGE:
            self._dim[("ko", m)] = d; d += 1
        for idx in range(len(field_2026.R32)):
            self._dim[("r32", idx)] = d; d += 1
        for g in GROUP_LETTERS:
            for pi in range(len(PAIRS)):
                self._dim[("grp", g, pi)] = d; d += 1
        self.n_dims = d
        # The uniform source for the *current* simulation. Default = crude MC, so
        # an unconfigured Tournament behaves exactly like before (the live path).
        self.src: qmc.UniformSource = qmc.PRNGSource(self.rng)

    def _real_score(self, home: str, away: str) -> tuple[int, int] | None:
        """The actual result for this pairing, if it has been played (either
        orientation — scores swapped to match the asked order)."""
        r = self.real_results.get((home, away))
        if r is not None:
            return r
        r = self.real_results.get((away, home))
        return (r[1], r[0]) if r is not None else None

    def _sample_score(self, home: str, away: str, dim: int) -> tuple[int, int]:
        key = (home, away)
        cached = self._grid_cache.get(key)
        if cached is None:
            grid, _, _ = self.pred.goals.scoreline_grid(home, away, neutral=True)
            flat = []
            for i, row in enumerate(grid):
                for j, p in enumerate(row):
                    flat.append(((i, j), p))
            cached = flat
            self._grid_cache[key] = flat
        r = self.src.u(dim)                 # QMC dimension (or PRNG for crude MC)
        cum = 0.0
        for score, p in cached:
            cum += p
            if r <= cum:
                return score
        return cached[-1][0]

    def _knockout(self, a: str, b: str, dim: int) -> str:
        """Single match; on a sampled draw, settle by relative win odds.
        A pairing that has really been played returns its real winner."""
        real = self._real_score(a, b)
        if real is not None:
            ha, hb = real
            if ha != hb:
                return a if ha > hb else b
            w = self.real_shootouts.get((a, b)) or self.real_shootouts.get((b, a))
            if w in (a, b):
                return w                  # drawn KO, known shootout winner
            ha, hb = 0, 0                 # drawn, winner unknown → odds coin below
        else:
            ha, hb = self._sample_score(a, b, dim)
        if ha > hb:
            return a
        if hb > ha:
            return b
        pr = self.pred.predict(a, b, neutral=True)
        denom = pr["p_home"] + pr["p_away"]
        pa = pr["p_home"] / denom if denom > 0 else 0.5
        return a if self.src.rand() < pa else b      # shoot-out coin (incidental)

    def simulate_once(self, groups: dict[str, list[str]]) -> dict:
        """Play one whole tournament; return reached-stage per team."""
        stage = {t: "group" for g in groups.values() for t in g}
        group_tables = {}
        group_pts: dict[str, int] = {}    # team -> group-stage points (control variate)
        thirds = []                       # (group, team, pts, gd, gf)
        win_by_g, run_by_g = {}, {}

        for g, teams in groups.items():
            stats = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}
            for pi, (i, j) in enumerate(PAIRS):
                h, a = teams[i], teams[j]
                real = self._real_score(h, a)
                hs, as_ = real if real is not None else \
                    self._sample_score(h, a, self._dim[("grp", g, pi)])
                self._apply(stats, h, a, hs, as_)
            ranked = sorted(teams, key=lambda t: (stats[t]["pts"], stats[t]["gd"],
                                                  stats[t]["gf"], self.src.rand()),
                            reverse=True)
            group_tables[g] = ranked
            for t in teams:
                group_pts[t] = stats[t]["pts"]
            win_by_g[g] = ranked[0]
            run_by_g[g] = ranked[1]
            t3 = ranked[2]
            thirds.append((g, t3, stats[t3]["pts"], stats[t3]["gd"], stats[t3]["gf"]))

        best = sorted(thirds, key=lambda x: (x[2], x[3], x[4], self.src.rand()),
                      reverse=True)[:8]
        third_groups = {g: t for g, t, *_ in best}     # group letter -> team

        for t in (list(win_by_g.values()) + list(run_by_g.values())
                  + list(third_groups.values())):
            stage[t] = "r32"

        champion = self._play_bracket(win_by_g, run_by_g, third_groups, stage)
        return {"stage": stage, "champion": champion, "groups": group_tables,
                "points": group_pts}

    def _assign_thirds(self, third_groups: dict) -> dict:
        """Map the eight 'T##' slots to third-placed teams, respecting Annex C.

        Backtracking with a most-constrained-slot heuristic; FIFA's allowed-group
        ranges guarantee a valid assignment exists for any set of eight qualifying
        third-place groups.
        """
        allowed = field_2026.ALLOWED_THIRDS
        avail = list(third_groups.keys())
        assign: dict[str, str] = {}

        def backtrack(remaining, used):
            if not remaining:
                return True
            remaining.sort(key=lambda s: sum(
                1 for g in avail if g in allowed[s] and g not in used))
            s = remaining[0]
            cands = [g for g in avail if g in allowed[s] and g not in used]
            self.src.shuffle(cands)
            for g in cands:
                assign[s] = g
                if backtrack(remaining[1:], used | {g}):
                    return True
                del assign[s]
            return False

        if not backtrack(list(allowed.keys()), set()):
            free = [g for g in avail if g not in assign.values()]   # defensive
            for s in allowed:
                if s not in assign:
                    assign[s] = free.pop()
        return {s: third_groups[g] for s, g in assign.items()}

    def _play_bracket(self, win_by_g, run_by_g, third_groups, stage) -> str:
        """Play the fixed 2026 bracket; update `stage` per team, return champion."""
        slot = {}
        for g in win_by_g:
            slot["1" + g] = win_by_g[g]
            slot["2" + g] = run_by_g[g]
        slot.update(self._assign_thirds(third_groups))

        results = {}
        for idx, (m, s1, s2) in enumerate(field_2026.R32):
            w = self._knockout(slot[s1], slot[s2], self._dim[("r32", idx)])
            results[m] = w
            stage[w] = "r16"
        for m in (89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 104):
            s1, s2 = field_2026.BRACKET[m]
            w = self._knockout(results[s1], results[s2], self._dim[("ko", m)])
            results[m] = w
            stage[w] = field_2026.WINNER_STAGE[m]
        return results[104]

    @staticmethod
    def _apply(stats, h, a, hs, as_):
        stats[h]["gf"] += hs; stats[a]["gf"] += as_
        stats[h]["gd"] += hs - as_; stats[a]["gd"] += as_ - hs
        if hs > as_:
            stats[h]["pts"] += 3
        elif as_ > hs:
            stats[a]["pts"] += 3
        else:
            stats[h]["pts"] += 1; stats[a]["pts"] += 1

    def run(self, runs: int | None = None, groups: dict | None = None,
            persist: bool = True, verbose: bool = True,
            method: str = "mc", qmc_seed: int | None = None,
            qmc_dims: int = 15) -> dict:
        """method: 'mc' (crude Monte Carlo, the default / live path),
        'qmc' (randomised scrambled-Halton) or 'antithetic' (mirrored pairs).

        qmc_dims caps how many (highest-leverage) dimensions QMC drives — the
        final→R16 knockouts sit on the lowest, best-distributed Halton bases;
        higher dimensions fall back to PRNG, where scrambled Halton would only
        add noise (see models/qmc.py self-test)."""
        runs = runs or config.SIM_RUNS
        if groups is None:
            # Use the official 2026 final draw as a fixed bracket. (Fall back to
            # a random Elo-pot draw only if the official groups are unavailable.)
            official = getattr(field_2026, "OFFICIAL_GROUPS", None)
            if official:
                groups = {g: teams[:] for g, teams in official.items()}
            else:
                pots = make_pots(field_2026.FIELD, self.elo)
                groups = draw_groups(pots, self.rng)

        order = {"group": 0, "r32": 1, "r16": 2, "qf": 3, "sf": 4, "final": 5, "champion": 6}
        reached = defaultdict(lambda: defaultdict(int))
        champ = defaultdict(int)

        halton = (qmc.ScrambledHalton(min(self.n_dims, qmc_dims), seed=qmc_seed)
                  if method == "qmc" else None)
        anti_vec = None

        for i in range(runs):
            # Pick the uniform source for this simulation. 'mc' reproduces the
            # original crude-MC behaviour; 'qmc'/'antithetic' reduce variance.
            if method == "qmc":
                self.src = qmc.QMCSource(halton.point(i), self.rng)
            elif method == "antithetic":
                if i % 2 == 0:
                    anti_vec = [self.rng.random() for _ in range(self.n_dims)]
                    self.src = qmc.QMCSource(anti_vec, self.rng)
                else:
                    self.src = qmc.QMCSource([1.0 - x for x in anti_vec], self.rng)
            else:
                self.src = qmc.PRNGSource(self.rng)
            res = self.simulate_once(groups)
            champ[res["champion"]] += 1
            for t, st in res["stage"].items():
                lvl = order[st]
                for s, o in order.items():
                    if o <= lvl:
                        reached[t][s] += 1

        teams = list(reached.keys())
        probs = {}
        for t in teams:
            probs[t] = {
                "p_win": champ[t] / runs,
                "p_final": reached[t]["final"] / runs,
                "p_semi": reached[t]["sf"] / runs,
                "p_quarter": reached[t]["qf"] / runs,
                "p_r16": reached[t]["r16"] / runs,
                "p_adv": reached[t]["r32"] / runs,   # advance out of the group
            }
        if verbose:
            self._report(probs, runs)
        if persist:
            self._persist(probs, runs)
        self._dump_json(groups, probs, runs)
        return {"groups": groups, "probs": probs, "runs": runs}

    @staticmethod
    def _report(probs, runs):
        ranked = sorted(probs.items(), key=lambda kv: kv[1]["p_win"], reverse=True)
        print(f"\n  Title odds ({runs:,} simulations):")
        print(f"  {'Team':<20}{'Win':>7}{'Final':>8}{'Semi':>8}{'QF':>8}")
        for t, p in ranked[:16]:
            print(f"  {t:<20}{p['p_win']:>6.1%}{p['p_final']:>8.1%}"
                  f"{p['p_semi']:>8.1%}{p['p_quarter']:>8.1%}")

    @staticmethod
    def _persist(probs, runs):
        with connect() as conn, conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO sim_results (runs, team, p_win, p_final, p_semi, p_quarter)
                VALUES (%s,%s,%s,%s,%s,%s)
                """,
                [(runs, t, p["p_win"], p["p_final"], p["p_semi"], p["p_quarter"])
                 for t, p in probs.items()],
            )

    def _dump_json(self, groups, probs, runs):
        """Write the report feeds (title odds + per-group advance odds) so
        FINDINGS.md regenerates from the live official-draw simulation."""
        ranked = sorted(probs.items(), key=lambda kv: kv[1]["p_win"], reverse=True)
        sim_report = {
            "runs": runs,
            "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "groups": {g: teams for g, teams in groups.items()},
            "title_odds": [
                {"team": t, "p_win": p["p_win"], "p_final": p["p_final"],
                 "p_semi": p["p_semi"], "p_quarter": p["p_quarter"]}
                for t, p in ranked
            ],
        }
        group_adv = {}
        for g, teams in groups.items():
            rows = sorted(teams, key=lambda t: self.elo.get(t, config.ELO_START),
                          reverse=True)
            group_adv[g] = [
                [t, round(self.elo.get(t, config.ELO_START)),
                 round(probs.get(t, {}).get("p_adv", 0.0) * 100)]
                for t in rows
            ]
        with open(os.path.join(config.DATA_DIR, "sim_report.json"), "w",
                  encoding="utf-8") as f:
            json.dump(sim_report, f, indent=1, ensure_ascii=False)
        with open(os.path.join(config.DATA_DIR, "group_adv.json"), "w",
                  encoding="utf-8") as f:
            json.dump(group_adv, f, indent=1, ensure_ascii=False)


if __name__ == "__main__":
    Tournament(seed=42).run(runs=3000)
