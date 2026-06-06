# WCPA — Live-Prediction & Content Playbook

What WCPA is, how it predicts the World Cup *live*, and the tools used to make original
content around it. Companion to **ASSETS.md** (licensing + Photopea recipe + AI prompts).

## The one-liner
WCPA — the **World Cup Prediction Album** — calls every match of the 2026 FIFA World Cup
with a statistical model backtested on 49,000+ internationals, laid out like a retro
Panini-style sticker album. Entertainment, **not** betting advice.

## How the live prediction works
An **ensemble**: international **Elo** (strength/form) blended with a time-decayed
**Dixon-Coles** Poisson goals model (scorelines + xG), calibrated and backtested
leakage-free — held-out **RPS 0.1667**, ~26% better than the base rate (see BACKTEST.md).

During the tournament it runs as a **live loop** (every 30–60 min on match days):
1. **Ingest** newest results + team news — `run.py ingest live` / `news`.
2. **Retrain** Elo + draw model + Dixon-Coles — `run.py train`.
3. **Re-simulate** 20,000 Monte-Carlo tournaments over the official R32→Final bracket —
   `run.py simulate 20000`.
4. **Re-export + redeploy** the static site to the CDN — `deploy.bat`
   (the build-cache skips the 4,500-prediction rebuild when nothing changed).

So title odds, group adv%, the wallchart and the **Match Centre** all move with the event.

**The live, accountable hook (the content angle):** every fixture gets a pre-match call —
win/draw/win, expected goals, likeliest scoreline. After it's played, the Match Centre
shows the real score *and* whether the model called it, with a running "called X of Y"
record. Public predictions, scored in the open, in real time.

## Content tooling (future content)
*All outputs must be ORIGINAL and follow the ASSETS.md copyright red-list — no FIFA marks,
no agency photos, no club crests, no real player likenesses — and you must confirm each
tool's commercial-use licence before publishing monetised content.*

- **Higgsfield AI** — generate **original cinematic / animated GUI & social visuals**:
  title stings, animated match-prediction cards, mascot motion, knockout-bracket reveals.
  AI-generated originals only; keep real marks/people out of every prompt.
  *(Confirm Higgsfield's commercial/licensing terms before using on the monetised site.)*
- **Photopea** — hand-finish stills to the vintage-album look (halftone / foil / grain
  recipe in ASSETS.md).
- **Pillow pipeline** — `python run.py ogcard` auto-generates the original share card
  (`og-cover.png`); extend it for per-match share cards later.
- **AI image prompts** — original mascot / crowd / stadium / foil-frame templates live in
  ASSETS.md (always append "no team names, no logos, no text, no real people").

## Shareable content ideas
- **Per-match cards**: a "WCPA calls it" pre-match card + a "called it ✓ / missed ✗" result.
- **Daily**: the model's record so far + the biggest upset vs the odds.
- **Stage gates**: group-stage wrap, the Round-of-32 wallchart reveal, title-odds shifts.
- Drive every post back to **wcpa26.com**; tip jar is **ko-fi.com/sambowey1110**.

---
*"higgfield" read as **Higgsfield AI** (generative video/image). Tell me if you meant a
different tool and I'll swap it through.*
