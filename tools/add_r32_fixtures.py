"""
Add/update all 16 R32 fixtures in the matches table.

Run once from the project root:
    python tools/add_r32_fixtures.py

What it does:
  - UPDATEs city/country/neutral on the 4 R32 rows already in the DB
    (South Africa/Canada, Brazil/Japan, Netherlands/Morocco, USA/Bosnia)
  - INSERTs the 12 missing R32 fixtures with full venue data
  - Skips any row that already exists (ON CONFLICT DO NOTHING)

Provisional team names are used where group J/K/L haven't finished yet
(they play today, 2026-06-27).  Run `python run.py ingest live` after
tonight's results to correct any wrong assignments.
"""

import sys
import os

# allow running from project root or from tools/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import config  # noqa: E402  loads .env
import db      # noqa: E402

# ── venue lookup ──────────────────────────────────────────────────────────────
# (home_team, away_team) -> (match_date, city, country)
R32_FIXTURES = [
    # M73
    ("South Africa",             "Canada",                   "2026-06-28", "Inglewood",      "United States"),
    # M74
    ("Germany",                  "Sweden",                   "2026-06-29", "Foxborough",     "United States"),
    # M75 – already in DB, needs venue
    ("Netherlands",              "Morocco",                  "2026-06-30", "Guadalupe",      "Mexico"),
    # M76 – already in DB, needs venue
    ("Brazil",                   "Japan",                    "2026-06-29", "Houston",        "United States"),
    # M77
    ("France",                   "Paraguay",                 "2026-06-30", "East Rutherford","United States"),
    # M78
    ("Ivory Coast",              "Norway",                   "2026-06-30", "Arlington",      "United States"),
    # M79
    ("Mexico",                   "Ecuador",                  "2026-07-01", "Mexico City",    "Mexico"),
    # M80
    ("England",                  "Senegal",                  "2026-07-01", "Atlanta",        "United States"),
    # M81 – already in DB, needs venue
    ("United States",            "Bosnia and Herzegovina",   "2026-07-02", "Santa Clara",    "United States"),
    # M82
    ("Belgium",                  "South Korea",              "2026-07-01", "Seattle",        "United States"),
    # M83
    ("Portugal",                 "Ghana",                    "2026-07-02", "Toronto",        "Canada"),
    # M84
    ("Spain",                    "Austria",                  "2026-07-02", "Inglewood",      "United States"),
    # M85
    ("Switzerland",              "Iran",                     "2026-07-03", "Vancouver",      "Canada"),
    # M86
    ("Argentina",                "Cape Verde",               "2026-07-03", "Miami Gardens",  "United States"),
    # M87
    ("Colombia",                 "Croatia",                  "2026-07-04", "Kansas City",    "United States"),
    # M88
    ("Australia",                "Egypt",                    "2026-07-03", "Arlington",      "United States"),
]

# The 4 rows already present in the DB (may have wrong/missing city+country)
EXISTING_PAIRS = {
    ("South Africa",  "Canada"),
    ("Brazil",        "Japan"),
    ("Netherlands",   "Morocco"),
    ("United States", "Bosnia and Herzegovina"),
}


def main():
    updated = 0
    inserted = 0
    skipped = 0

    existing = set(EXISTING_PAIRS)  # mutable copy

    with db.connect() as conn:
        for home, away, match_date, city, country in R32_FIXTURES:
            if (home, away) in existing:
                # UPDATE venue on the existing row
                cur = conn.execute(
                    """
                    UPDATE matches
                       SET city    = %s,
                           country = %s,
                           neutral = TRUE
                     WHERE tournament = 'FIFA World Cup'
                       AND home_team  = %s
                       AND away_team  = %s
                       AND match_date = %s
                    """,
                    (city, country, home, away, match_date),
                )
                if cur.rowcount:
                    print(f"  UPDATED  {home} vs {away}  ->  {city}, {country}")
                    updated += 1
                else:
                    print(f"  MISSING  {home} vs {away}  (expected row not found - will insert)")
                    existing.discard((home, away))  # fall through to INSERT below

            if (home, away) not in existing:
                # INSERT (unique key: match_date+home_team+away_team+tournament)
                cur = conn.execute(
                    """
                    INSERT INTO matches
                        (tournament, match_date, home_team, away_team,
                         neutral, city, country, status)
                    VALUES
                        ('FIFA World Cup', %s, %s, %s,
                         TRUE, %s, %s, 'scheduled')
                    ON CONFLICT (match_date, home_team, away_team, tournament)
                    DO NOTHING
                    """,
                    (match_date, home, away, city, country),
                )
                if cur.rowcount:
                    print(f"  INSERTED {home} vs {away}  ({match_date})  {city}, {country}")
                    inserted += 1
                else:
                    print(f"  SKIPPED  {home} vs {away}  (already exists)")
                    skipped += 1

    print(f"\nDone. updated={updated}  inserted={inserted}  skipped={skipped}")


if __name__ == "__main__":
    main()
