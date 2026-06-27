-- D1 schema for the Collapse daily leaderboard (database: wcpa-runs).
-- Apply once:  wrangler d1 execute wcpa-runs --remote --file=schema_runs.sql
-- Best run per handle per day (UNIQUE day+handle); ranked by the server-computed score.
-- ip_hash = sha256(day|client-ip): daily-rotating pseudonymous key for the
-- per-network handle cap (no raw IPs are ever stored).

CREATE TABLE IF NOT EXISTS runs (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  day           TEXT    NOT NULL,            -- daily challenge date (YYYY-MM-DD, UTC)
  handle        TEXT    NOT NULL,            -- player tag
  team          TEXT    NOT NULL,            -- nation played
  round_reached TEXT    NOT NULL,            -- group | r32 | r16 | qf | sf | final | champion
  round_score   INTEGER NOT NULL,            -- 0..6 ladder
  margin        INTEGER NOT NULL,            -- aggregate goal difference across the run
  seed          INTEGER NOT NULL,            -- daily seed (audit)
  champion      INTEGER NOT NULL DEFAULT 0,
  elo           INTEGER NOT NULL DEFAULT 1500,
  score         INTEGER NOT NULL,            -- server-computed leaderboard score
  ip_hash       TEXT    NOT NULL DEFAULT '', -- sha256(day|ip) — submission cap key
  created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_day_handle ON runs(day, handle);
CREATE INDEX IF NOT EXISTS idx_runs_rank ON runs(day, score DESC, created_at ASC);
CREATE INDEX IF NOT EXISTS idx_runs_day_ip ON runs(day, ip_hash);
