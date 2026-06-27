"""
One-shot DB fix: Canada vs Switzerland (2026-06-24) was ingested with teams
swapped — stored as Switzerland (home) 2-1 Canada (away) instead of the
canonical Canada (home) 1-2 Switzerland (away).

This left TWO rows in `matches` for the same fixture:
  A) Canada vs Switzerland  — no score (the originally-scheduled row)
  B) Switzerland vs Canada  — home_score=2, away_score=1 (the incorrect result)

This script:
  1. Updates row A with the correct score and marks it finished.
  2. Deletes row B.

Run once:
    python tools/fix_canada_switzerland.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import datetime as dt
from db import connect

TOURNAMENT = "FIFA World Cup"
MATCH_DATE = dt.date(2026, 6, 24)
WINDOW = dt.timedelta(days=1)

def run():
    with connect() as conn:
        # Row A — canonical record (Canada home, no score yet)
        row_a = conn.execute(
            """
            SELECT id, home_score, away_score, status FROM matches
            WHERE home_team='Canada' AND away_team='Switzerland'
              AND tournament=%s
              AND match_date BETWEEN %s AND %s
            ORDER BY abs(match_date - %s) LIMIT 1
            """,
            (TOURNAMENT, MATCH_DATE - WINDOW, MATCH_DATE + WINDOW, MATCH_DATE),
        ).fetchone()

        # Row B — incorrectly ingested record (Switzerland home, has score)
        row_b = conn.execute(
            """
            SELECT id, home_score, away_score, status FROM matches
            WHERE home_team='Switzerland' AND away_team='Canada'
              AND tournament=%s
              AND match_date BETWEEN %s AND %s
            ORDER BY abs(match_date - %s) LIMIT 1
            """,
            (TOURNAMENT, MATCH_DATE - WINDOW, MATCH_DATE + WINDOW, MATCH_DATE),
        ).fetchone()

        if not row_a and not row_b:
            print("Neither row found — nothing to fix.")
            return

        if row_a:
            print(f"  Row A (Canada home): id={row_a[0]}  score={row_a[1]}-{row_a[2]}  status={row_a[3]}")
        else:
            print("  Row A (Canada home): NOT FOUND")

        if row_b:
            print(f"  Row B (Switzerland home, wrong): id={row_b[0]}  score={row_b[1]}-{row_b[2]}  status={row_b[3]}")
        else:
            print("  Row B (Switzerland home): NOT FOUND — may already be clean")

        if row_a and row_b:
            # Correct state: update A with the flipped score from B, delete B.
            # The live feed recorded Switzerland 2-1 Canada (B's perspective).
            # In the canonical Canada-home view: Canada 1 – 2 Switzerland.
            correct_hs = row_b[2]   # B's away_score  = Canada's goals
            correct_as = row_b[1]   # B's home_score  = Switzerland's goals
            conn.execute(
                "UPDATE matches SET home_score=%s, away_score=%s, status='finished' WHERE id=%s",
                (correct_hs, correct_as, row_a[0]),
            )
            conn.execute("DELETE FROM matches WHERE id=%s", (row_b[0],))
            print(f"  ✓ Updated row A → home_score={correct_hs}, away_score={correct_as}, status=finished")
            print(f"  ✓ Deleted row B (id={row_b[0]})")

        elif row_b and not row_a:
            # No canonical row exists at all — fix row B in place by swapping
            # home/away teams and scores.
            correct_hs = row_b[2]
            correct_as = row_b[1]
            conn.execute(
                """
                UPDATE matches
                SET home_team='Canada', away_team='Switzerland',
                    home_score=%s, away_score=%s,
                    neutral=FALSE, city='Vancouver', country='Canada',
                    status='finished'
                WHERE id=%s
                """,
                (correct_hs, correct_as, row_b[0]),
            )
            print(f"  ✓ Fixed row B in place → Canada {correct_hs}-{correct_as} Switzerland, neutral=FALSE")

        elif row_a and not row_b:
            # Only the canonical row exists — just make sure it has the correct score.
            if row_a[1] is None:
                # Score is missing; we know the result was Canada 1-2 Switzerland.
                conn.execute(
                    "UPDATE matches SET home_score=1, away_score=2, status='finished' WHERE id=%s",
                    (row_a[0],),
                )
                print("  ✓ Row A had no score; applied known result: Canada 1-2 Switzerland")
            else:
                print("  Row A already has a score — no change needed.")

    print("\nDone. Re-run `python run.py export` to regenerate fixtures.json from the corrected DB.")


if __name__ == "__main__":
    run()
