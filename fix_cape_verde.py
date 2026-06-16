"""One-off cleanup: remove the orphan 'Cape Verde Islands' rows that football-data
inserted before the NAME_MAP fix (it now canonicalises to 'Cape Verde'). Those rows
have no matching `teams` entry, so `run.py train` fails the team_ratings FK.

Safe: the canonical 'Cape Verde' fixtures remain untouched and pick up the real
results on the next `python run.py ingest live`. Run once, then deploy:

    python fix_cape_verde.py
    deploy.bat
"""
from db import connect

BAD = "Cape Verde Islands"

with connect() as c:
    n = c.execute(
        "DELETE FROM matches WHERE home_team=%s OR away_team=%s", (BAD, BAD)
    ).rowcount
    # defensive: clear any stray rating/team rows (FK order: ratings before teams)
    for tbl, col in (("team_ratings", "team"), ("teams", "name")):
        try:
            c.execute(f"DELETE FROM {tbl} WHERE {col}=%s", (BAD,))
        except Exception as e:
            print(f"  ({tbl} skip: {e})")
    print(f"removed {n} '{BAD}' match row(s); canonical 'Cape Verde' fixtures kept")
