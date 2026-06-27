# WCPA — Visual Assets & Licensing Guide

How WCPA sources visuals. **Rule: original or open-license only.** This is a monetised
AU site, so every asset must allow **commercial use + redistribution**. "Free for
personal use" fails the test. *(Research basis below; not legal advice — re-check each
asset's licence badge at download, and consider an IP review for high-stakes use.)*

## Hard red list — never use
- **FIFA marks**: World Cup emblem, trophy likeness, official mascot, "FIFA World Cup"
  wordmark (trademark; the trophy is a protected 3-D work). → Original tournament
  identity / original cup *silhouette* that resembles no real trophy.
- **Panini** artwork, sticker scans, album-page scans (copyright). → Recreate the
  *structure* (squared portrait, pennant, name+nation, 2-page spread) with original art.
- **News-agency photos** — Getty / AP / Reuters / AFP / Alamy (rights-managed; actively
  litigated via Pixsy/Copytrack). → CC0 museum art + own generated imagery.
- **Real player photos or likenesses** (photographer copyright + personality rights). →
  Generic faceless / original characters only; no identifiable real people.
- **Club crests / kits / sponsor logos** (trademark). → Invented pennants + public-domain
  flags (flagcdn, already used). Avoid federation logos.
- **"Free for personal use"** tiers (much of Freepik free, dafont personal-use fonts,
  "free brush" packs); **rawpixel non-PD "Free Images"**; **Texturelabs** redistribution
  or AI-training use; **Twemoji** without the required CC-BY credit.

## Safe sources (commercial-OK)
**Fonts** — every Google Font is SIL OFL 1.1 / Apache-2.0: commercial, embeddable, no UI
credit. Current stack (Anton, Bungee, Staatliches, Space Grotesk) is already clear. Stat
numerals: JetBrains Mono / Space Mono. Self-hosting these OFL TTFs also drops the Google
Fonts external dependency (privacy + tighter CSP).
**Textures** (paper/halftone/foil/grunge) — **#1: fake in CSS/SVG (zero licence)**; else
CC0: ambientcg.com (CC0), rawpixel Public-Domain items, Library of Congress "free to use".
**Vintage illustrations (CC0)** — The Met Open Access, Smithsonian Open Access, Art
Institute of Chicago, Cleveland Museum of Art, rawpixel Public-Domain, Openverse (filter
to CC0). AU-local: State Library Victoria copyright-free image search; Trove (verify
per-item — its status flag is an estimate, not legal advice).
**Icons (MIT/ISC — keep the LICENSE file in-tree, no visible credit)** — Phosphor (has a
soccer-ball glyph), Tabler, Lucide, Heroicons.

## Photopea recipe — base art → vintage album
Photopea is free and reads/writes .psd. Layer stack, bottom → top:
1. **Paper base** — CC0 grain, or solid warm off-white `#F2E9D8`.
2. **Original artwork** above it.
3. **Halftone it** — duplicate → desaturate → *Filter ▸ Pixelate ▸ Color Halftone*
   (radius 4–8px); set the layer to **Multiply** so dots sit into the paper.
4. **Limited ink** — clip a Gradient-Map / Hue-Sat to crush to 2–4 spot colours.
5. **Misregistration** — split a colour layer, nudge 1–3px, **Multiply** (offset = print error).
6. **Foil panel** — metallic gradient → **Screen**/**Overlay** + diagonal highlight + Bevel.
7. **Paper grain on top** — **Multiply** 15–35% so the whole composite shares one surface.
8. **Dust/scratches** (CC0) — **Screen**, low opacity.
9. **Global warm tone** — Curves/Photo-Filter; export flattened PNG/WebP.

Blend logic: **Multiply** = ink-into-paper · **Screen** = foil shine / white dust ·
**Overlay** = grain bite.

## Original AI generation (era feel, zero real marks)
Every prompt: describe **era + medium + technique**, never a real team/player/artist, and
**append**: *"no team names, no logos, no text, no brand marks, no real people, no
copyrighted characters."* Sanity-check each render for accidental marks. Templates:
- **Mascot** — "Original vintage soccer mascot, friendly anthropomorphic [lion/kangaroo/
  globe] in a plain retro kit with NO logos or text, kicking a ball; 1960s–70s
  sports-program illustration, bold outlines, flat 3-colour palette (orange/teal/cream),
  halftone shading, slight print misregistration on textured paper. No team names, no
  brand marks, no real people."
- **Crowd** — "Stylised 1970s terraces, generic scarves/pennants in flat colour blocks,
  faceless figures, risograph, 2–3 spot colours, heavy grain, halftone. No logos, no
  readable text, no identifiable people."
- **Stadium** — "Vintage illustrated stadium at dusk, floodlight pylons, retro
  sports-poster style, limited ink palette, halftone sky, paper grain + slight layer
  offset. No real stadium, no signage, no brand marks."
- **Foil frame** — "Original foil sticker frame, starburst + laurel motif, metallic
  silver-gold gradient with diagonal shine, 1980s collectible bevel on textured card.
  Abstract, no logos/text, no emblem resembling any real organisation."

## Content & motion tooling (future content)
For original animated / cinematic GUI + social content: **Higgsfield AI** (generative
video/image — title stings, animated prediction cards, mascot motion). AI-generated
**originals only**, same red-list as above (no FIFA marks, agency photos, crests or real
players), and confirm Higgsfield's **commercial licence** before monetised use. Hand-finish
stills in **Photopea** (recipe above); automate share cards with the **Pillow** pipeline
(`run.py ogcard`). See **CONTENT.md** for the live-prediction + content playbook.

## This repo
- Palette + type live in `viz/static/style.css` `:root` (`--paper`, `--gold`, `--terra`,
  `--ink`…). Decorative grain/halftone are already CSS/SVG (`.grain`, `.halftone`).
- **Pillow build-time pipeline**: `python run.py ogcard` → original `viz/static/og-cover.png`
  (1200×630). OFL fonts live in `viz/assets/fonts/` with their licence kept alongside.
  Pillow is **build-time only** — the static site and live server need none of it.
- Collector vernacular for empty/CTA states: "got · got · need", "swapsies", "shinies".
