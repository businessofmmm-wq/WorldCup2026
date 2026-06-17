# Three.js r128 → modern (r184) — upgrade assessment

_Scope: the 3D Overview (`viz/static/overview3d.js`), loaded by `app.js` from
cdnjs `three.js/r128/three.min.js` (UMD global `window.THREE`). Researched Jun 2026._

## Verdict
**Defer until a quiet window (post group-stage).** r128 is working, now optimised
(deduped textures, render-on-demand, offscreen pause) and depends on **no addons**
(we hand-rolled the orbit controls). The upgrade is future-proofing, not a fix — and
the one real cost is the module system, not our logic.

## What actually breaks (only these touch WCPA)
1. **No more UMD build.** three dropped the UMD `three.min.js` around r150; modern
   releases ship ES modules only (`three.module.js` + an import map). Our loader
   (`<script src=…three.min.js>` → `window.THREE`) won't work on r184. **This is the
   main migration item.**
2. **Colour management on by default (r152+).** `renderer.outputEncoding` →
   `renderer.outputColorSpace = THREE.SRGBColorSpace`; texture `.encoding` →
   `.colorSpace`; `THREE.sRGBEncoding` → `THREE.SRGBColorSpace`. We currently set
   `renderer.outputEncoding`/`t.encoding` behind an `'outputEncoding' in renderer`
   guard, so on r184 it silently no-ops → flags render slightly dark until switched
   to the new API.
3. **`useLegacyLights = false` by default (r155+).** Light intensities are scaled
   differently. Our flags are `MeshBasicMaterial` (unlit) so they're unaffected; only
   the ambient/point "mood" lights need a small intensity re-tune.
4. Non-issues: we already use `BufferGeometry`/`Float32BufferAttribute` (legacy
   `Geometry` was removed long ago), and we use **no** `examples/jsm` addons.

## Migration options
- **A — stay on r128** (now). Zero risk during the live tournament. ✅ current.
- **B — ESM via import map from a CDN.** `import * as THREE from 'three'`. Needs a CDN
  that serves `three.module.js` (jsdelivr / unpkg / esm.sh) **added to the CSP**
  (today CSP allows cdnjs only) — a server/headers change.
- **C — self-host a pinned `three.module.js`** in `viz/static/` and import it
  (recommended). No CSP/CDN dependency, version locked, matches the "static album"
  model. ~150 KB gzipped added to the export.

## When you do it (Option C checklist)
1. Drop `viz/static/three.module.js` (a pinned release, e.g. r16x/r18x).
2. `overview3d.js`: replace `const THREE = window.THREE` with
   `import * as THREE from './three.module.js'`; in `app.js` stop injecting the cdnjs
   `<script>` and just dynamic-import overview3d (it pulls three itself).
3. Swap colour API: `renderer.outputColorSpace = THREE.SRGBColorSpace`;
   every flag/canvas texture `t.colorSpace = THREE.SRGBColorSpace` (drop the
   `outputEncoding`/`encoding` guards).
4. Re-tune `AmbientLight`/`PointLight` intensities for `useLegacyLights=false`
   (roughly: multiply by ~Math.PI, then eyeball).
5. CSP: allow the self-hosted module (same-origin — no change needed if self-hosted).
6. Device test (esp. iPhone Safari) + confirm `overview3DAvailable()` still gates.

## Upside
Long-term support, the WebGPU renderer path, correct colour by default, and access to
modern addons if ever needed. None of it is user-visible today — so it's a maintenance
investment, best done when not racing live match-day deploys.

Sources: three.js r184 release notes; color-management roadmap (#23614); useLegacyLights PR #25479; WebGPU + three.js migration guide (2026).
