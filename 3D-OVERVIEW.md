# WCPA26 — 3D Overview · Build Brief (handoff for next session)

Status: **prototyped in chat (Three.js), not yet on the site.** This doc is the
compact plan to build it into `viz/static` as the recoded Overview (page `#whole`).

## 1. Goal & locked decisions
- Recode the Overview (`#whole`) as an **interactive 3D scene**, fully replacing the
  2D mural, with the 2D mural kept as a **fallback** (no-WebGL / `prefers-reduced-motion`).
- Theme: **digital World Cup history** — gold/ink/charcoal + holographic foil
  (see `MOODBOARD` content below), real flags, cinematic motion.
- Shape: a **navigable cascade of stages** — Group(48) → R32 → R16 → QF → SF → Final → Champion(1).
- Two data modes: **Prediction** (model projection + odds) and **Reality** (real
  results; each played game signified with a score + ✓/✗ badge; future stages "awaiting").
- **Only the selected stage is interactive** (raycast that stage only); others dim as context.
- **Free-roam camera**: drag = look, WASD = move, Q/E = down/up, scroll = zoom; the
  stage rail / ‹ › / ←→ fly the camera to a stage and set the active (interactive) stage.

## 2. Prototype feature spec (already working in the widget)
- Flag engine: procedural `<canvas>` flags (real colours + patterns: tricolours, crosses,
  Brazil rhombus, US canton, Japan disc, etc.) with gold frame, gloss overlay, **team code
  chip (bottom-left)** + **group letter chip (top-right)**. → On the LIVE site swap these
  for real `flagcdn` SVG textures (sharper).
- Group stage = **12 labelled clusters A–L** (pot-seeded 4-each in the proto; use real draw live).
- Knockout stages = grids of the advancers; champion = **metallic gold trophy** + glow.
- **Gold "write-the-future" path** (TubeGeometry) through the #1 seed of each stage to the trophy;
  travelling spark in Prediction mode.
- Waving cloth flags (vertex sine displacement) on the **active stage only**.
- GUI: breadcrumb (top-left), mode toggle (top-centre), selection panel (top-right:
  swatch + name + GROUP + RANK + odds/result), stage rail (bottom), controls hint.

## 3. OPTIMAL 3D REPRESENTATION — analysis & recommendation
Data layers and their best encodings:
| Layer | Honest 2D encoding (precise) | 3D encoding (experiential) |
|---|---|---|
| Title odds (48 probs) | ranked bars / heatmap | node size + brightness; podium |
| Advance prob per group | **Sankey** (FiveThirtyEight) | **flow-ribbon width ∝ P(advance)** |
| Bracket / path | wallchart | gold chalk path (have it) |
| Live results | match cards | score + ✓/✗ badges (have it) |

**Recommendation — a navigable 3D Sankey funnel.** Keep the cascade, but make the
**connectors between stages ribbons whose thickness = probability mass** advancing, and
**size/brighten nodes by title odds**. That upgrades the pretty funnel into a *data-honest*
view and directly borrows FiveThirtyEight's proven Sankey idea in 3D. The modal champion
stays the gold path.

**Caveat (important):** 3D perspective distorts precise value comparison. So 3D is the
**hero/experience layer**; a **precise 2D view is one toggle away** — reuse the existing
mural (groups + river + odds) or add a flat Sankey + knockout heatmap. This mirrors how the
best data orgs ship it (clarity first, spectacle second).

Models considered & verdict:
- Cascade/funnel (chosen) — best 48→1 narrative + navigable.
- 3D Sankey ribbons (fold into cascade) — most data-honest; **do this**.
- Probability terrain / orbital "solar system" — evocative but imprecise; skip for v1.

## 4. Reference projects (what "optimal wcpa26.com" looks like)
- **FiveThirtyEight World Cup** — the gold standard: **Sankey for group stage**
  (P(advance)) + **sorted heatmap for knockout**; 10k sims, updates each match.
  https://fivethirtyeight.com/interactives/world-cup · data: https://github.com/fivethirtyeight/data/tree/master/world-cup-predictions
- **Opta supercomputer (theanalyst.com)** — 10k–25k sims, group-by-group probabilistic
  previews; static articles (our edge = **live updating**, already built).
  https://theanalyst.com/articles/who-will-win-2026-fifa-world-cup-predictions-opta-supercomputer
- **clubelo.com / eloratings.net** — Elo-over-time line charts; minimalist, data-first.
  http://clubelo.com/ · https://www.eloratings.net/
- **Bracketry / Flourish tournament charts** — clean 2D bracket libs (good fallback patterns).
  https://bracketry.app/ · https://flourish.studio/visualisations/tournament-chart/
- **3D viz craft**: 3D interactive brackets are rare → novelty/differentiation, but ground it
  in real data. Perf bible: https://discoverthreejs.com/tips-and-tricks/ ·
  https://tympanus.net/codrops/2025/07/10/three-js-instances-rendering-multiple-objects-simultaneously/

Takeaway for "optimal wcpa26.com": **FiveThirtyEight/Opta rigor** (Sankey groups,
knockout heatmap, method/calibration transparency) **+ the album's identity** + a
**signature 3D experiential Overview** + **live updates** (our differentiator) + a fast,
accessible **2D precise view** always one click away.

## 5. Performance plan (live port)
- ~111 flags → use **`InstancedMesh` + a flag texture atlas** (one draw call), not 111 meshes.
  Target **<100 draw calls**, 60fps. (discoverthreejs / codrops instancing.)
- Wave only the active stage; **LOD**/skip vertex updates for distant stages.
- Real flags: one **texture atlas** built from flagcdn SVGs at load (or a sprite sheet shipped in repo).
- Dispose geometries/materials on teardown; cap `pixelRatio` at 2.

## 6. Live port plan (into viz/static)
- New module `viz/static/overview3d.js` (ES module, like collapse.js). `index.html` `#whole`
  gets a `<canvas>` + the 2D mural kept as fallback markup (shown if WebGL/3D unavailable or reduced-motion).
- Data: read existing feeds — `/api/groupadv.json` (groups + adv%), `/api/bracket.json`
  (R32→champion + winners), `/api/report.json` (title_odds), `/api/fixtures.json`
  (real results + live-match detection → Reality badges). Reuse `ensureData()` + `STATE`.
- Click a flag → open the existing **condensed profile card** (`showProfile(team, el, true)`).
- **Three.js hosting decision (OPEN):** self-host `three.min.js` in `viz/static` (matches the
  no-third-party CSP philosophy; ~170 KB) **or** allow `cdnjs` in CSP (`script-src`). Lean self-host.
  If self-host: drop `three.min.js` into `viz/static/`, load via `<script>`, no CSP change.
  If CDN: update CSP in `viz/export.py` `_cdn_config` (the `_headers`) **and** `viz/server.py`.
- Verify (jsdom smoke for data wiring + the 2D fallback path) → ship via the unified **`deploy.bat`**
  (export → verify → push). Same flag-cdn img-src already allowed.

## 7. Open decisions for Sam (answer next session)
1. Self-host Three.js vs allow CDN in CSP? (recommend self-host)
2. 3D fully replaces the mural, or 3D hero + the 2D mural/precise view one toggle below? (recommend keep a 2D precise toggle)
3. Add the data-honest **Sankey ribbons** (width = P(advance)) to the cascade for v1, or ship the
   plain cascade first and layer ribbons later?

## 8. MOODBOARD recap (palette + motion kit)
Palette: Ink #0e0c0a · Charcoal #1c1a17 · Gold #e3a512 (hi #f2c33b) · Cream #efe2c2 ·
Pitch/Teal #2ea88a · Accents #c1272d / #1e4db7 · Foil ['#d9c7ff','#9fe7d0','#ffe9a8','#ffb0c8','#9fd0ff'].
Motion kit: write-the-future path · bloom glow · particle/gold dust · speed-ramp fly-in ·
podium reveal + count-up odds · foil shimmer · waving flags.
Type: Anton/Bungee (heavy condensed, kinetic) — already self-hosted on the site.
