-- World Cup 2026 prediction engine — PostgreSQL schema.
-- Idempotent: safe to run repeatedly (CREATE ... IF NOT EXISTS).

-- ---------------------------------------------------------------------------
-- Reference: teams (national sides). Name is the natural key used everywhere
-- so it lines up directly with the historical dataset's team strings.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS teams (
    name          TEXT PRIMARY KEY,
    confederation TEXT,            -- UEFA / CONMEBOL / CONCACAF / CAF / AFC / OFC
    fifa_code     TEXT,            -- 3-letter code when known
    is_active     BOOLEAN DEFAULT TRUE
);

-- ---------------------------------------------------------------------------
-- Every international match (historical + live). Goals + xG where available.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS matches (
    id           BIGSERIAL PRIMARY KEY,
    match_date   DATE NOT NULL,
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    home_score   INTEGER,          -- NULL = not yet played
    away_score   INTEGER,
    home_xg      REAL,             -- expected goals (StatsBomb / live), NULL if unknown
    away_xg      REAL,
    tournament   TEXT,
    city         TEXT,
    country      TEXT,
    neutral      BOOLEAN DEFAULT FALSE,
    source       TEXT,             -- 'martj42' | 'sportsdb' | 'statsbomb'
    status       TEXT DEFAULT 'finished',  -- finished | scheduled | live
    UNIQUE (match_date, home_team, away_team, tournament)
);
CREATE INDEX IF NOT EXISTS idx_matches_date ON matches (match_date);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches (home_team);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches (away_team);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches (status);

-- Penalty shootouts (knockout matches that finished level).
CREATE TABLE IF NOT EXISTS shootouts (
    match_date  DATE NOT NULL,
    home_team   TEXT NOT NULL,
    away_team   TEXT NOT NULL,
    winner      TEXT,
    PRIMARY KEY (match_date, home_team, away_team)
);

-- ---------------------------------------------------------------------------
-- Model outputs. team_ratings = latest Elo + Dixon-Coles attack/defence.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS team_ratings (
    team          TEXT PRIMARY KEY REFERENCES teams(name),
    elo           REAL,
    attack        REAL,             -- Dixon-Coles attack strength (log scale)
    defence       REAL,             -- Dixon-Coles defence strength (log scale)
    matches_count INTEGER,
    last_match    DATE,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- Full Elo history so we can chart a team's trajectory over time.
CREATE TABLE IF NOT EXISTS elo_history (
    team       TEXT NOT NULL,
    match_date DATE NOT NULL,
    elo        REAL NOT NULL,
    PRIMARY KEY (team, match_date)
);

-- Stored match predictions (every time we predict a fixture we log it, so we
-- can score the model's calibration after the fact).
CREATE TABLE IF NOT EXISTS predictions (
    id           BIGSERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ DEFAULT now(),
    match_date   DATE,
    home_team    TEXT NOT NULL,
    away_team    TEXT NOT NULL,
    neutral      BOOLEAN DEFAULT TRUE,
    p_home       REAL,             -- P(home win)
    p_draw       REAL,
    p_away       REAL,
    exp_home_goals REAL,
    exp_away_goals REAL,
    top_scoreline  TEXT,           -- e.g. '1-1'
    model        TEXT,             -- 'ensemble' | 'elo' | 'dixon_coles'
    detail       JSONB             -- full scoreline grid + component probs
);

-- ---------------------------------------------------------------------------
-- Live news feed. One row per article; team tags + flags drive alerts.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS news (
    id          BIGSERIAL PRIMARY KEY,
    fetched_at  TIMESTAMPTZ DEFAULT now(),
    published   TIMESTAMPTZ,
    source      TEXT,
    title       TEXT,
    link        TEXT UNIQUE,
    summary     TEXT,
    teams       TEXT[],           -- national teams mentioned
    flags       TEXT[]            -- injury / suspension / form / lineup / transfer
);
CREATE INDEX IF NOT EXISTS idx_news_published ON news (published DESC);

-- Tournament simulation snapshots (advancement / win probabilities per run).
CREATE TABLE IF NOT EXISTS sim_results (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ DEFAULT now(),
    runs        INTEGER,
    team        TEXT,
    p_win       REAL,             -- P(lift the trophy)
    p_final     REAL,
    p_semi      REAL,
    p_quarter   REAL,
    UNIQUE (created_at, team)
);
