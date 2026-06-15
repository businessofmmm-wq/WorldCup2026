# WCPA · Goal Theatre (APP)

A standalone, single-file web app that **reconstructs how a goal happened** — every
pass, carry and the finishing shot, animated on a pitch — so people can see the goal
without watching the match. Shares the wcpa26.com look (gold/ink/charcoal) and pulls
the same live fixtures feed.

Open `index.html` in any browser (double-click works — sample data is embedded).

## What's in it
- **Live match rail** — tries `wcpa26.com/api/fixtures.json` (live/final/scheduled
  states); falls back to bundled sample fixtures offline.
- **Goal Theatre** — a 120×80 pitch (StatsBomb coordinate system) with a playback
  engine: play/pause, restart, scrub, 0.5×/1×/2× speed. Ball follows the move; passes,
  carries (dashed) and the shot are colour-coded; the shot draws the GK + defenders
  from the freeze-frame and ripples the net.
- **"How it unfolded" feed** — the event list, highlighting in time with the replay.

## Data model (the important part)
Each goal is an object in the `GOALS` array, in the **StatsBomb open-data event
schema** so real data plugs straight in:

```js
{
  id, team, scorer, minute, assist, label, sub,
  events:[
    {min, sec, type:"pass"|"carry"|"shot", player, loc:[x,y], end:[x,y],
     freeze:[{x,y,gk?}]   // defenders/GK, on the shot only
    }, ...
  ]
}
```
Coordinates are 0–120 (length) × 0–80 (width), attacking toward x=120 — identical to
StatsBomb. To replay a **real historical goal**: pull the match events JSON from
[statsbomb/open-data](https://github.com/statsbomb/open-data), take the possession
chain ending in the shot, map each event's `type` + `location` + `pass.end_location`
into the shape above (the shot's `shot.freeze_frame` becomes `freeze`).

## The live-2026 data reality
A true positional replay needs **player/ball positions**, which free live feeds don't
provide:
- **football-data.org** (the new live-results feed) → score, scorer, minute only. Good
  for a live scorer/minute timeline, not a positional reconstruction.
- **StatsBomb open data** → full positions + freeze-frames, but **historical** matches.
- **Paid** (StatsBomb live, Opta, Sportradar) → positional data for live 2026.

So: finished matches with event data get the full reconstruction; live 2026 goals show
as a scorer/minute timeline until a paid positional feed is added.

## Roadmap
1. Auto-build `GOALS` from a StatsBomb match file (mapper script).
2. Live scorer/minute timeline from `footballdata.event_timeline_by_match()`.
3. Player names/numbers on markers; multi-goal match navigation from the rail.
4. PWA shell (installable) + share-card export of a goal.
