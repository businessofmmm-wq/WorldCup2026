"""
Fix the 7 provisional R32 fixtures that were wrong when the real bracket
was announced after the group stage (Jun 27→28 2026).

Run once:
    python tools/fix_r32_fixtures.py

Changes:
  Germany  vs Sweden     → Germany  vs Paraguay   (M74)
  France   vs Paraguay   → France   vs Sweden      (M77)
  England  vs Senegal    → England  vs DR Congo    (M80)
  Belgium  vs South Korea → Belgium vs Senegal     (M82)
  Portugal vs Ghana      → Portugal vs Croatia     (M83 slot; confirmed)
  Switzerland vs Iran    → Algeria  vs Switzerland (M85)
  Colombia vs Croatia    → Colombia vs Ghana       (M87 slot)

For each wrong fixture:
  1. DELETE the old row (wrong teams)
  2. INSERT the correct row (or UPDATE if already present from footballdata feed)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db  # noqa: E402

# (old_home, old_away) -> (correct_home, correct_away, match_date, city, country)
FIXES = [
    ("Germany",     "Sweden",      "Germany",    "Paraguay",             "2026-06-29", "Foxborough",    "United States"),
    ("France",      "Paraguay",    "France",     "Sweden",               "2026-06-30", "East Rutherford","United States"),
    ("England",     "Senegal",     "England",    "DR Congo",             "2026-07-01", "Atlanta",        "United States"),
    ("Belgium",     "South Korea", "Belgium",    "Senegal",              "2026-07-01", "Seattle",        "United States"),
    ("Portugal",    "Ghana",       "Portugal",   "Croatia",              "2026-07-02", "Toronto",        "Canada"),
    ("Switzerland", "Iran",        "Algeria",    "Switzerland",          "2026-07-03", "Vancouver",      "Canada"),
    ("Colombia",    "Croatia",     "Colombia",   "Ghana",                "2026-07-04", "Kansas City",    "United States"),
]


def main():
    deleted = inserted = updated = skipped = 0
    with db.connect() as conn:
        for old_h, old_a, new_h, new_a, match_date, city, country in FIXES:
            # 1. Delete the wrong provisional row (if it still exists)
            cur = conn.execute(
                "DELETE FROM matches "
                "WHERE tournament='FIFA World Cup' AND home_team=%s AND away_team=%s "
                "AND match_date=%s AND home_score IS NULL",
                (old_h, old_a, match_date),
            )
            if cur.rowcount:
                print(f"  DELETED  {old_h} vs {old_a}  ({match_date})")
                deleted += 1
            else:
                print(f"  MISSING  {old_h} vs {old_a}  — may already have been corrected")

            # 2. Upsert the correct fixture (footballdata may have already added it)
            # First try exact match
            exists = conn.execute(
                "SELECT id FROM matches "
                "WHERE tournament='FIFA World Cup' AND home_score IS NULL "
                "AND ((home_team=%s AND away_team=%s) OR (home_team=%s AND away_team=%s)) "
                "AND match_date BETWEEN %s::date-1 AND %s::date+1",
                (new_h, new_a, new_a, new_h, match_date, match_date),
            ).fetchone()

            if exists:
                # Update venue on the existing row (it may have come from footballdata)
                conn.execute(
                    "UPDATE matches SET city=%s, country=%s, neutral=TRUE "
                    "WHERE id=%s",
                    (city, country, exists[0]),
                )
                print(f"  UPDATED  {new_h} vs {new_a}  — venue set to {city}, {country}")
                updated += 1
            else:
                conn.execute(
                    "INSERT INTO matches "
                    "(tournament, match_date, home_team, away_team, "
                    " neutral, city, country, status) "
                    "VALUES ('FIFA World Cup',%s,%s,%s,TRUE,%s,%s,'scheduled') "
                    "ON CONFLICT (match_date, home_team, away_team, tournament) DO NOTHING",
                    (match_date, new_h, new_a, city, country),
                )
                print(f"  INSERTED {new_h} vs {new_a}  ({match_date})")
                inserted += 1

    print(f"\nDone. deleted={deleted}  inserted={inserted}  updated={updated}")
    print("Next: python run.py export && deploy")


if __name__ == "__main__":
    main()
