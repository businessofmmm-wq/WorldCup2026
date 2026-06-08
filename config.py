"""
Central configuration for the World Cup 2026 prediction engine.

Everything tunable lives here. Connection string follows the same override
pattern as Samuel's other projects (MMM / MarketMind): read an env var if set,
otherwise fall back to the local PostgreSQL 17 server.
"""
from __future__ import annotations
import os

# --------------------------------------------------------------------------- #
# Local .env loader (no dependency — keeps the tiny-deps ethos)
# --------------------------------------------------------------------------- #
# Secrets (the database URL, optional API keys) live in a gitignored .env file
# at the project root, never in source. Load it into the environment before any
# config value is read. Real environment variables always win over .env, so
# production/CI can override by exporting the var. See .env.example for format.
def _load_dotenv(path: str) -> None:
    try:
        with open(path, encoding="utf-8-sig") as fh:  # utf-8-sig tolerates a BOM
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                # strip surrounding quotes if present; do not override real env
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
# The connection string comes from the environment (WORLDCUP_DATABASE_URL, or
# the shared DATABASE_URL), normally via the local .env file. No credential is
# baked into source — the same code points at a managed cloud Postgres in
# production just by setting the env var.
DATABASE_URL = (
    os.environ.get("WORLDCUP_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
)
if not DATABASE_URL:
    raise RuntimeError(
        "No database URL configured. Set WORLDCUP_DATABASE_URL (or DATABASE_URL) "
        "in your environment, or create a .env file at the project root. "
        "Copy .env.example to .env and fill in your local Postgres credentials."
    )

# --------------------------------------------------------------------------- #
# Data sources (all public / free)
# --------------------------------------------------------------------------- #
# The master historical dataset: every men's international since 1872.
# Maintained by martj42, mirrored on GitHub. CSV, no key needed.
RESULTS_BASE = "https://raw.githubusercontent.com/martj42/international_results/master"
RESULTS_CSV = f"{RESULTS_BASE}/results.csv"        # date,home,away,scores,tournament,city,country,neutral
SHOOTOUTS_CSV = f"{RESULTS_BASE}/shootouts.csv"    # penalty shootout winners
GOALSCORERS_CSV = f"{RESULTS_BASE}/goalscorers.csv"  # per-goal scorer/minute/penalty

# Live fixtures, results and tables. Free public test key "3".
SPORTSDB_KEY = os.environ.get("SPORTSDB_KEY", "3")
SPORTSDB_BASE = f"https://www.thesportsdb.com/api/v1/json/{SPORTSDB_KEY}"
# TheSportsDB league id for the FIFA World Cup.
SPORTSDB_WC_LEAGUE_ID = "4429"

# StatsBomb free open data — shot-level events incl. xG for World Cups.
STATSBOMB_BASE = "https://raw.githubusercontent.com/statsbomb/open-data/master/data"
# Competition ids in the open data: 43 = FIFA World Cup, 72 = Women's World Cup.
STATSBOMB_WC_COMP = 43

# News RSS feeds — international / world football focused.
NEWS_FEEDS = [
    ("BBC Sport Football", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Guardian Football", "https://www.theguardian.com/football/rss"),
    ("Sky Sports Football", "https://www.skysports.com/rss/12040"),
    ("ESPN Soccer", "https://www.espn.com/espn/rss/soccer/news"),
]

# --------------------------------------------------------------------------- #
# Model parameters
# --------------------------------------------------------------------------- #
# Elo — tuned to the widely used World Football Elo Ratings conventions.
ELO_START = 1500.0          # rating for a previously unseen team
ELO_HOME_ADVANTAGE = 65.0   # points added to the home side (0 on neutral grounds)
ELO_K_SCALE = 1.0           # global multiplier on every K-factor (backtest-tuned)
ELO_DRAW_MAX = 0.30         # max draw mass for an evenly-matched tie (Elo 1X2 model)
ELO_USE_GD = True           # scale K by the goal-difference multiplier

# K-factor scales by tournament importance (World Football Elo weights).
ELO_K_BY_TOURNAMENT = {
    "FIFA World Cup": 60.0,
    "FIFA World Cup qualification": 40.0,
    "UEFA Euro": 50.0,
    "UEFA Euro qualification": 40.0,
    "Copa América": 50.0,
    "African Cup of Nations": 50.0,
    "AFC Asian Cup": 50.0,
    "CONCACAF Gold Cup": 50.0,
    "UEFA Nations League": 40.0,
    "Confederations Cup": 45.0,
    "Friendly": 20.0,
}
ELO_K_DEFAULT = 30.0        # any tournament not in the table above

# Dixon-Coles / Poisson.
DC_HALF_LIFE_DAYS = 600.0   # exponential time-decay: older matches matter less
DC_MAX_GOALS = 8            # truncate the scoreline grid at this many goals
DC_RECENT_YEARS = 12        # only fit attack/defence on matches this recent
DC_RHO = -0.11              # Dixon-Coles low-score correlation correction
DC_ITERS = 400              # gradient-ascent iterations for the MLE fit
DC_LR = 0.40                # learning rate (step = avg residual * lr)
DC_REG = 0.08               # L2 shrinkage on attack/defence (curbs minnow overfit)

# Goals model selecting the JOINT scoreline law (the marginals — time-decayed
# attack/defence — are shared either way):
#   "bivpois"     -> bivariate Poisson with a fitted shared covariance lambda3,
#                    a proper joint distribution (models/bivpoisson.py).
#   "dixon_coles" -> independent Poisson + the four-cell tau low-score patch.
# Held-out verdict (`run.py backtest 2022 --compare`): a near-tie — DC a hair
# better in the production ensemble (RPS 0.1685 vs 0.1688) because BP's
# lambda3>=0 can't represent the slight NEGATIVE goal dependence DC's tau does
# (lambda3 fits to ~0 on pre-test data). Shipping the proper bivariate model by
# choice; to be settled definitively next session (full 2018 backtest +
# diagonal-inflated BP). Flip back to "dixon_coles" to revert — both stay wired.
GOALS_MODEL = "bivpois"

# Bivariate-Poisson shared covariance (models/bivpoisson.py).
BP_MAX_LAMBDA3 = 0.5        # upper bracket for the 1-D MLE of the shared term l3
BP_LAMBDA3_FALLBACK = 0.0   # l3 used by load() when no fitted params file exists

# Ensemble weighting between the Elo 1X2 and the goals-model (DC/BP) 1X2.
ENSEMBLE_ELO_WEIGHT = 0.45
ENSEMBLE_DC_WEIGHT = 0.55
# Final temperature applied to the blended 1X2 (p_i ** (1/T), renormalised).
# T<1 sharpens, T>1 softens; 1.0 = no-op. Fit by `run.py calibrate`.
ENSEMBLE_TEMPERATURE = 1.0

# Monte Carlo.
SIM_RUNS = 20000

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)

# --------------------------------------------------------------------------- #
# Backtest-tuned overrides
# --------------------------------------------------------------------------- #
# `python run.py tune` writes data/tuned_params.json with the parameter set that
# minimised held-out RPS. If present, it overrides the defaults above so the
# tuned model flows straight into predict / train / simulate. Delete the file to
# revert to the hand-set defaults. Keys map 1:1 to the constants below.
_TUNABLE = {
    "ELO_K_SCALE", "ELO_HOME_ADVANTAGE", "ELO_DRAW_MAX", "ELO_USE_GD",
    "DC_HALF_LIFE_DAYS", "DC_REG", "DC_RHO",
    "ENSEMBLE_ELO_WEIGHT", "ENSEMBLE_DC_WEIGHT", "ENSEMBLE_TEMPERATURE",
}
_TUNED_FILE = os.path.join(DATA_DIR, "tuned_params.json")
try:
    import json as _json
    with open(_TUNED_FILE, encoding="utf-8") as _fh:
        for _k, _v in _json.load(_fh).items():
            if _k in _TUNABLE:
                globals()[_k] = _v
except (FileNotFoundError, ValueError):
    pass
