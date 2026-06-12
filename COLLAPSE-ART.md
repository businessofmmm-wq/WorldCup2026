# Collapse — Higgsfield art brief (optional, green-lane)

The game ships and looks complete with **procedural visuals** (the canvas superposition
heatmap, the collapse animation, the album palette). These Higgsfield slots are purely
to lift the polish — each has a graceful fallback, so drop them in whenever.

**Hard rules (from `ASSETS.md`):** original AI art only. No FIFA/World-Cup marks, no club
crests/kits, no real player likenesses, no real logos, **no text in the image**. Abstract
"physics × football" — that's the whole aesthetic and it keeps us green-lane.

Palette to echo: off-black `#141310`, cream `#efe2c2`, the daily accents (green
`#009C3B` / red `#C1272D`), warm gold. Grainy, halftone, matte — "offset print", not glossy 3D.

## Slots
| File (drop into `viz/static/assets/collapse/`) | Use | Prompt seed |
|---|---|---|
| `hero.webp` (1600×900) | setup-screen banner | "a football dissolving into a cloud of probability — particles and faint scoreline grids drifting off a leather ball into dark space, halftone print texture, muted green and red risograph inks, no text" |
| `op-coherence.webp` … `op-tunnel.webp` (square 600²) | one per operator chip | per operator: **Coherence** "converging light rays focusing to a single bright point"; **Superposition Press** "one ball split into many overlapping ghost images"; **Observer's Wall** "a measuring grid freezing a wave into still bars"; **Entanglement** "two linked orbits sharing one thread of light"; **Tunneling** "a faint ball passing through a solid barrier, leaving a glow" — all abstract, risograph, no text |
| `collapse-bg.webp` (1200×1200) | behind the collapse canvas | "a probability field collapsing inward to one glowing cell, radial, dark, green/gold particles" |
| `card-bg.webp` (1080×1350) | run-end share card background | "vertical poster: a single bright timeline thread cutting through a faded lattice of unrealised futures, dark, grainy, room for type" |

## Wiring (when assets land)
- Setup hero: add `<div class="cl-hero">` at the top of `renderSetup()` with `background-image`,
  fallback = the existing gradient.
- Operator chips: `cl-op` already has a `.cl-op-glyph`; add `background-image` per `data-id`
  in CSS (`.cl-op[data-id="coherence"]{...}`), fallback = the glyph + accent tint already shown.
- Collapse canvas: draw `collapse-bg` under the cells in `drawField` if loaded (else the dark
  panel, as now).
- Share card: in `downloadCard`, `drawImage(cardBg)` first if loaded (else the solid `--bg`, as now).

All four fallbacks are already live, so none of this blocks launch.
