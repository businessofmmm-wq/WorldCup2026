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
from collections import defaultdict

import config
from db import connect
from models.predict import Predictor
from models import field_2026


GROUP_LETTERS = [chr(ord("A") + i) for i in range(12)]


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


class Tournament:
    def __init__(self, predictor: Predictor | None = None, seed: int | None = None):
        self.pred = predictor or Predictor()
        self.elo = self.pred.elo
        self.rng = random.Random(seed)
        # cache scoreline grids per ordered pair (neutral) — big speed win
        self._grid_cache: dict[tuple, tuple] = {}

    def _sample_score(self, home: str, away: str) -> tuple[int, int]:
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
        r = self.rng.random()
        cum = 0.0
        for score, p in cached:
            cum += p
            if r <= cum:
                return score
        return cached[-1][0]

    def _knockout(self, a: str, b: str) -> str:
        """Single match; on a sampled draw, settle by relative win odds."""
        ha, hb = self._sample_score(a, b)
        if ha > hb:
            return a
        if hb > ha:
            return b
        pr = self.pred.predict(a, b, neutral=True)
        denom = pr["p_home"] + pr["p_away"]
        pa = pr["p_home"] / denom if denom > 0 else 0.5
        return a if self.rng.random() < pa else b

    def simulate_once(self, groups: dict[str, list[str]]) -> dict:
        """Play one whole tournament; return reached-stage per team."""
        stage = {t: "group" for g in groups.values() for t in g}
        group_tables = {}
        thirds = []
        winners, runners = [], []

        for g, teams in groups.items():
            stats = {t: {"pts": 0, "gd": 0, "gf": 0} for t in teams}
            for i in range(len(teams)):
                for j in range(i + 1, len(teams)):
                    h, a = teams[i], teams[j]
                    hs, as_ = self._sample_score(h, a)
                    self._apply(stats, h, a, hs, as_)
            ranked = sorted(teams, key=lambda t: (stats[t]["pts"], stats[t]["gd"],
                                                  stats[t]["gf"], self.rng.random()),
                            reverse=True)
            group_tables[g] = ranked
            winners.append(ranked[0])
            runners.append(ranked[1])
            third = ranked[2]
            thirds.append((third, stats[third]["pts"], stats[third]["gd"], stats[third]["gf"]))

        best_thirds = [t for t, *_ in sorted(
            thirds, key=lambda x: (x[1], x[2], x[3], self.rng.random()), reverse=True)[:8]]

        r32 = winners + runners + best_thirds          # 32 teams
        for t in r32:
            stage[t] = "r32"

        # Bracket: shuffle the 32 into 16 ties (a fair proxy for the seeding map).
        self.rng.shuffle(r32)
        rounds = [("r16", 16), ("qf", 8), ("sf", 4), ("final", 2), ("champion", 1)]
        survivors = r32
        for name, _size in rounds:
            nxt = []
            for k in range(0, len(survivors), 2):
                w = self._knockout(survivors[k], survivors[k + 1])
                nxt.append(w)
            for t in nxt:
                stage[t] = name
            survivors = nxt
        return {"stage": stage, "champion": survivors[0], "groups": group_tables}

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
            persist: bool = True, verbose: bool = True) -> dict:
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

        for _ in range(runs):
            # re-draw groups each run only if not a fixed draw
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
