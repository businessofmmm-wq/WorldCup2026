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

# --------------------------------------------------------------------------- #
# Quantum Tactics Lab — computer-vision pipeline (LOCAL, build-time only).
# These tune tools/cv_tactics.py. They are read ONLY when `run.py cv` runs; no
# serving path imports cv2/ultralytics. Upgraded from the yolov8-nano default to a
# higher-capacity detector at higher input resolution for micro-detailed precision
# (more players found, tighter boxes, the ball picked up). Override via env to trade
# precision for speed, e.g. WCPA_YOLO_WEIGHTS=yolov8s.pt WCPA_YOLO_IMGSZ=960.
#   yolov8n (nano) < s < m < l < x (extra-large, most precise, slowest on CPU)
YOLO_WEIGHTS = os.environ.get("WCPA_YOLO_WEIGHTS", "yolov8x.pt")
YOLO_IMGSZ = int(os.environ.get("WCPA_YOLO_IMGSZ", "1280"))   # inference resolution
YOLO_CONF = float(os.environ.get("WCPA_YOLO_CONF", "0.20"))   # keep faint/distant players
YOLO_IOU = float(os.environ.get("WCPA_YOLO_IOU", "0.5"))      # NMS overlap
CV_HEATMAP_NX = 12          # occupancy heatmap columns (along the pitch length)
CV_HEATMAP_NY = 8           # occupancy heatmap rows (across the pitch width)
CV_DETECT_BALL = True       # also detect the ball (COCO 'sports ball', class 32)

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
#   "bivpois"          -> bivariate Poisson with a fitted shared covariance lambda3,
#                         a proper joint distribution (models/bivpoisson.py).
#   "bivpois_diag"     -> diagonal-inflated BP: adds an explicit diagonal_factor
#                         that boosts tied-score cells (0-0, 1-1, 2-2, etc.) to
#                         increase draw mass beyond the BP baseline. Fit via 1-D MLE.
#   "dixon_coles"      -> independent Poisson + the four-cell tau low-score patch.
# Held-out verdict — SETTLED on the full window (`run.py backtest 2018 --compare`,
# 8,009 held-out matches from 2018-01-01): bivariate-Poisson now WINS on the goals
# model alone (RPS 0.1686 vs DC 0.1691; better LogLoss 0.8681 and Brier 0.5084
# too), and lambda3 fits to a healthy +0.058 on the modern window — the coupling
# is real here, not collapsed as it was pre-2022. In the full Elo+goals ensemble
# the two are a dead heat (RPS 0.1668 BP vs 0.1667 DC — a 4th-decimal, noise-level
# gap). So bivpois stays the default. The diagonal-inflated BP offers a 3rd
# experimental option; backtest it via `run.py backtest --compare` to validate.
GOALS_MODEL = "bivpois"

# Bivariate-Poisson shared covariance (models/bivpoisson.py).
BP_MAX_LAMBDA3 = 0.5        # upper bracket for the 1-D MLE of the shared term l3
BP_LAMBDA3_FALLBACK = 0.0   # l3 used by load() when no fitted params file exists

# Diagonal-inflated BP parameters (models/bivpoisson.fit_diagonal).
BP_DIAG_MAX_FACTOR = 2.0    # upper bracket for diagonal inflation factor
BP_DIAG_FACTOR_FALLBACK = 1.0  # factor used by load_diagonal() when no params file

# Ensemble weighting between the Elo 1X2 and the goals-model (DC/BP) 1X2.
ENSEMBLE_ELO_WEIGHT = 0.45
ENSEMBLE_DC_WEIGHT = 0.55
# Final temperature applied to the blended 1X2 (p_i ** (1/T), renormalised).
# T<1 sharpens, T>1 softens; 1.0 = no-op. Fit by `run.py calibrate`.
ENSEMBLE_TEMPERATURE = 1.0
# Optional per-class temperature [T_home, T_draw, T_away] (models/calibrate.py).
# When set (not None), it overrides the scalar above — an extra 2 DoF that lowers
# calibration error (ECE) on the asymmetric 1X2 draw class. None = use scalar.
# Fit via models.calibrate.fit_vector_temperature; keep only if backtest improves.
ENSEMBLE_TEMPERATURE_VEC = None
# Shrinkage toward the base-rate prior: p' = (1-λ)·p + λ·prior. Curbs slight
# over-confidence, lowering Brier/RPS. λ=0 = off. Fit via calibrate.fit_shrinkage;
# ENSEMBLE_PRIOR is the [home, draw, away] base rate (calibrate.base_rate).
ENSEMBLE_SHRINKAGE = 0.0
ENSEMBLE_PRIOR = None

# Tournament-form overlay (models/form.py): once WC2026 games are played, nudge a
# team's *effective* Elo by how it performed vs the model's own expectation in this
# tournament so far — recency-weighted and bounded so one game can't swing it. Flows
# through the Elo half of the ensemble. FORM_WEIGHT = 0 disables it. TUNE BY BACKTEST.
FORM_WEIGHT = 0.5            # blend fraction of the form delta into Elo (0 = off)
FORM_K = 30.0               # per-game Elo-point scale before weighting (a K-factor)
FORM_CAP = 70.0             # max |form delta| per team across the whole tournament
FORM_HALFLIFE_DAYS = 12.0   # recency half-life (older tournament games count for less)
FORM_WINDOW_START = "2026-06-01"   # only matches on/after this date count as "form"
FORM_XG_WEIGHT = 0.5        # blend "deserved" (xG) result into the form signal (0 = ignore xG)
FORM_XG_SCALE = 0.9         # logistic scale mapping the xG margin -> deserved-win prob

# Monte Carlo — the tournament held as a superposition of every possible future,
# sampled run-by-run; each run is one collapsed "world". More runs resolve the
# possibility space more finely (lean on models/variance.py — QMC/antithetic/
# control-variate — to keep 50k cheap). This is the information->matter step:
# raw probabilities become the tangible album once exported.
SIM_RUNS = 50000

# The live inflow loop (`run.py refresh`, every ~30 min on match days) re-sims on
# a tight budget: it must stay fast, and the *authoritative* odds come from the
# 50k `simulate` path, not from here. So run the fewest worlds that still hold the
# live title bars steady between refreshes. Antithetic (mirrored-pair) sampling
# roughly doubles precision-per-run, so 1,500 antithetic runs ~= 3k crude on the
# title/advancement numbers the snapshot shows — a >3x cut from the old 5k crude.
# The sim is rarely the refresh bottleneck anyway (network ingest + the 49k-row
# Elo/DC refit dominate). Keeps every data string in the loop, just expands it
# efficiently. Revert with REFRESH_METHOD = "mc", REFRESH_RUNS = 5000.
REFRESH_RUNS = 1500
REFRESH_METHOD = "antithetic"   # 'mc' | 'qmc' | 'antithetic' (models/tournament.py)

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
    "ENSEMBLE_TEMPERATURE_VEC", "ENSEMBLE_SHRINKAGE", "ENSEMBLE_PRIOR",
    "FORM_XG_WEIGHT", "FORM_XG_SCALE",
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
