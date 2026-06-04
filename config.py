"""
Central configuration for the World Cup 2026 prediction engine.

Everything tunable lives here. Connection string follows the same override
pattern as Samuel's other projects (MMM / MarketMind): read an env var if set,
otherwise fall back to the local PostgreSQL 17 server.
"""
from __future__ import annotations
import os

# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #
# Same role/server as the rest of the stack, dedicated `worldcup` database.
DATABASE_URL = (
    os.environ.get("WORLDCUP_DATABASE_URL")
    or os.environ.get("DATABASE_URL")
    or "postgresql://mmm_app:mmm_local_dev@localhost:5432/worldcup"
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

# Ensemble weighting between the Elo 1X2 and the Dixon-Coles 1X2.
ENSEMBLE_ELO_WEIGHT = 0.45
ENSEMBLE_DC_WEIGHT = 0.55

# Monte Carlo.
SIM_RUNS = 20000

# --------------------------------------------------------------------------- #
# Paths
# --------------------------------------------------------------------------- #
ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
os.makedirs(DATA_DIR, exist_ok=True)
