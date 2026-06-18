"""
Tournament-form overlay on Elo.

Now that WC2026 games are being played, nudge each team's *effective* rating by
how it has performed versus the model's OWN expectation in this tournament so far.
The signal is deliberately conservative: one game is weak, so each team's form
delta is recency-weighted and clamped to ±FORM_CAP, and only FORM_WEIGHT of it is
blended into Elo. It flows through the Elo half of the ensemble (predict.py).

This does not invent player/tactical data it doesn't have — it is purely "results
vs expectation in this tournament", which is exactly what 'current form' means at
the team level. Tune FORM_WEIGHT (and friends) with `run.py backtest` before relying
on it; FORM_WEIGHT = 0 disables the overlay entirely.
"""
from __future__ import annotations
import datetime as dt

import config
from db import connect
from models import elo as elo_mod


def _clamp(v: float, cap: float) -> float:
    return max(-cap, min(cap, v))


def compute_form(base_elo: dict, *, as_of: dt.date | None = None) -> dict:
    """Return {team: form_delta_elo} from finished current-tournament matches.

    Replays this tournament's finished games in order; each game moves both teams
    by K * gd_mult * (actual - expected) * recency_decay, where `expected` uses the
    base Elo plus form accrued so far (so a second result compounds sensibly). The
    running delta is clamped to ±FORM_CAP. Read-only; never raises fatally.
    """
    if config.FORM_WEIGHT <= 0:
        return {}
    try:
        with connect() as conn:
            rows = conn.execute(
                """
                SELECT match_date, home_team, away_team, home_score, away_score, neutral
                FROM matches
                WHERE status='finished' AND home_score IS NOT NULL AND away_score IS NOT NULL
                  AND tournament ILIKE %s AND match_date >= %s
                ORDER BY match_date, id
                """,
                ("%World Cup%", config.FORM_WINDOW_START),
            ).fetchall()
    except Exception:
        return {}

    today = as_of or dt.date.today()
    half = max(1.0, float(config.FORM_HALFLIFE_DAYS))
    cap = float(config.FORM_CAP)
    form: dict[str, float] = {}
    for d, home, away, hs, as_, neutral in rows:
        ra = base_elo.get(home, config.ELO_START) + form.get(home, 0.0)
        rb = base_elo.get(away, config.ELO_START) + form.get(away, 0.0)
        ha = 0.0 if neutral else config.ELO_HOME_ADVANTAGE
        exp = elo_mod.expected_score(ra + ha, rb)            # home win-expectancy
        actual = 1.0 if hs > as_ else 0.0 if hs < as_ else 0.5
        gd_mult = elo_mod._gd_multiplier(hs - as_) if config.ELO_USE_GD else 1.0
        try:
            age = (today - d).days if isinstance(d, dt.date) else 0
        except Exception:
            age = 0
        decay = 0.5 ** (max(0, age) / half)
        delta = config.FORM_K * gd_mult * (actual - exp) * decay
        form[home] = _clamp(form.get(home, 0.0) + delta, cap)
        form[away] = _clamp(form.get(away, 0.0) - delta, cap)
    return form


def effective_elo(base_elo: dict, *, as_of: dt.date | None = None) -> dict:
    """base Elo + FORM_WEIGHT * (clamped form delta). Returns base unchanged if the
    overlay is off or there are no current-tournament results yet."""
    f = compute_form(base_elo, as_of=as_of)
    if not f:
        return base_elo
    w = float(config.FORM_WEIGHT)
    out = dict(base_elo)
    for t, delta in f.items():
        out[t] = out.get(t, config.ELO_START) + w * delta
    return out


if __name__ == "__main__":
    from models.predict import _load_elo
    base = _load_elo()
    f = compute_form(base)
    print(f"form overlay (weight {config.FORM_WEIGHT}, {len(f)} teams):")
    for t, d in sorted(f.items(), key=lambda kv: -abs(kv[1]))[:16]:
        print(f"   {t:<22} {d:+6.1f}  -> eff {base.get(t, config.ELO_START) + config.FORM_WEIGHT*d:7.1f}")
