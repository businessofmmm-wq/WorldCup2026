# Live feed swap → football-data.org (WC)

Replaces the TheSportsDB live-results inflow with football-data.org v4. martj42
history and StatsBomb xG are untouched; `viz/server.py` still uses `sportsdb` for
its best-effort goal timelines.

## Code changes (already in the repo)
- `sources/footballdata.py` — new. Drop-in for the old live module: same
  `ingest(verbose=True) -> dict` contract, writes into `matches` with
  `source='footballdata'`, canonicalises team names to martj42 spellings, and uses
  the same ±1-day / never-overwrite-a-score-with-NULL defensive write path.
- `run.py` line 49 — `from sources import footballdata as src_live`
  (was `sportsdb`). Both `ingest live` and `refresh` route through `src_live`, so
  this one line switches the feed everywhere.

## What you do (one input)
1. Create a free account and token: https://www.football-data.org/client/register
   — the free tier is 10 requests/min, plenty for 5-min polling.
2. Add it as a GitHub repo secret named **`WCPA_FOOTBALLDATA_TOKEN`**
   (Settings → Secrets and variables → Actions → New repository secret).
3. Expose it to the two workflows that run the engine — add this to the step env
   in `.github/workflows/wcpa-deploy.yml` and `.github/workflows/wcpa-refresh.yml`
   (alongside the existing `WORLDCUP_DATABASE_URL` etc.):

   ```yaml
   env:
     WCPA_FOOTBALLDATA_TOKEN: ${{ secrets.WCPA_FOOTBALLDATA_TOKEN }}
   ```
4. For local testing, add the same line to your `.env`:
   ```
   WCPA_FOOTBALLDATA_TOKEN=your_token_here
   ```

## Verify
```
python -m sources.footballdata      # smoke test: prints live/finished WC matches
python run.py ingest live           # the real path
python run.py health                # finished_matches should tick up after games
```
The module prints a warning for any team name not in the 48-team field — if you see
one during a live matchday, add the feed's spelling to `NAME_MAP` in
`sources/footballdata.py`.

## Notes
- Polling cadence is unchanged — it's driven by `wcpa-refresh.yml` (5-min during
  kickoff windows), and `ingest live` just calls the new module.
- `sources/sportsdb.py` is left in place (timelines + as a fallback). To switch
  back, revert the one import line in `run.py`.
- Optional upgrade: `footballdata.event_timeline_by_match(match_id)` returns goal
  minute + scorer + assist from the per-match endpoint — richer than the free
  TheSportsDB timeline. `viz/server.py` could adopt it later.
