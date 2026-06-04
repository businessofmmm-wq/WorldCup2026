"""
Database access layer. Thin wrapper over psycopg 3.

Connections are short-lived and opened per call via a context manager — fine
for a batch/CLI workload and keeps things simple. Schema init is idempotent.
"""
from __future__ import annotations
import os
from contextlib import contextmanager

import psycopg

import config


@contextmanager
def connect():
    """Yield a connection; commit on clean exit, rollback on error."""
    conn = psycopg.connect(config.DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    """Create all tables/indexes if they do not already exist."""
    schema_path = os.path.join(config.ROOT, "schema.sql")
    with open(schema_path, "r", encoding="utf-8") as fh:
        sql = fh.read()
    with connect() as conn:
        conn.execute(sql)


def health() -> dict:
    """Return a quick snapshot of the database state."""
    out: dict = {"connected": False}
    try:
        with connect() as conn:
            out["connected"] = True
            for label, q in (
                ("matches", "SELECT count(*) FROM matches"),
                ("finished_matches", "SELECT count(*) FROM matches WHERE status='finished' AND home_score IS NOT NULL"),
                ("teams", "SELECT count(*) FROM teams"),
                ("rated_teams", "SELECT count(*) FROM team_ratings"),
                ("news", "SELECT count(*) FROM news"),
                ("predictions", "SELECT count(*) FROM predictions"),
            ):
                try:
                    out[label] = conn.execute(q).fetchone()[0]
                except psycopg.errors.UndefinedTable:
                    conn.rollback()
                    out[label] = "—"
            try:
                row = conn.execute(
                    "SELECT min(match_date), max(match_date) FROM matches"
                ).fetchone()
                out["date_range"] = f"{row[0]} → {row[1]}" if row[0] else "—"
            except psycopg.errors.UndefinedTable:
                conn.rollback()
    except Exception as exc:  # pragma: no cover
        out["error"] = str(exc)
    return out


def upsert_team(conn, name: str, confederation: str | None = None,
                fifa_code: str | None = None) -> None:
    """Insert a team if new; fill in confederation/code if we learn them."""
    conn.execute(
        """
        INSERT INTO teams (name, confederation, fifa_code)
        VALUES (%s, %s, %s)
        ON CONFLICT (name) DO UPDATE
          SET confederation = COALESCE(EXCLUDED.confederation, teams.confederation),
              fifa_code     = COALESCE(EXCLUDED.fifa_code, teams.fifa_code)
        """,
        (name, confederation, fifa_code),
    )
