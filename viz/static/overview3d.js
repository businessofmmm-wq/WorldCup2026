/* =====================================================================
   WCPA · 3D OVERVIEW  (feature module — progressive enhancement)
   Navigable Three.js cascade of the tournament (Group 48 -> Champion 1) wired
   to the real feeds, with data-honest Sankey ribbons between stages (width ∝
   each team's probability of reaching the next stage), nodes scaled by title
   odds, the champion's route in gold. Self-guarding; mounts into a dedicated
   container so the 2D mural stays as the fallback; destroy() tears down.

   2026 refresh + optimisation:
     • Flags load as raster PNG from flagcdn (w320/<iso>.png) — SVG-as-texture
       rasterises to an empty/black plane; PNG is reliable. sRGB-encoded, size-
       guarded (a bad load keeps the coloured fallback tile), and DEDUPED per
       nation: one fetch + one GPU texture shared across every stage a team
       appears in (~100 loads -> ~48).
     • Constrained-orbit navigation: drag / one finger = orbit, wheel / two-
       finger pinch = zoom, tap a stage (or ‹ ›, arrow keys) to fly there.
     • Render-on-demand: the GPU loop runs only while the view is moving or a
       texture just arrived, and pauses entirely when the canvas is offscreen
       or the tab is hidden — idle cost ≈ 0.
   Enable: host three.min.js r128 same-origin in viz/static.
   ===================================================================== */
'use strict';

const GOLD = 0xe3a512, GOLDHI = 0xf2c33b, INK = 0x0e0c0a;
function hexToRgb(h) { h = (h || '#5a6b86').replace('#', ''); if (h.length === 3) h = h.split('').map(x => x + x).join('');
  const n = parseInt(h, 16) || 0; return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255]; }

export function overview3DAvailable() {
  if (typeof window === 'undefined' || !window.THREE) return false;
  try { const c = document.createElement('canvas');
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl')); }
  catch (e) { return false; }
}

export function initOverview3D(mount, data, onPick, hooks) {
  if (!overview3DAvailable() || !mount) return null;
  const THREE = window.THREE;

  // ---- derive cascade + probability lookups from REAL feeds ----
  const odds = (data.report && data.report.title_odds) || [];
  const ranked = odds.map(o => o.team), oddsOf = {}, ROAD = {};
  odds.forEach(o => { oddsOf[o.team] = o.p_win; ROAD[o.team] = { pw: o.p_win, pq: o.p_quarter, ps: o.p_semi, pf: o.p_final }; });
  const ga = data.groupadv || {};
  const groups = Object.keys(ga).sort().map(k => ({ name: k, teams: ga[k] }));
  const flagOf = {}, isoOf = {}, ccOf = {}, ADV = {};
  const note = c => { if (!c || !c.team) return; if (c.flag) flagOf[c.team] = c.flag;
    if (c.iso2) isoOf[c.team] = c.iso2; if (c.confed_color) ccOf[c.team] = c.confed_color; };
  groups.forEach(g => g.teams.forEach(t => { note(t); ADV[t.team] = (t.adv || 0) / 100; }));
  odds.forEach(note);
  const B = data.bracket || {}, R = B.rounds || {};
  const both = ties => (ties || []).flatMap(t => [t.a, t.b]).filter(Boolean);
  const winners = ties => (ties || []).map(t => (t.winner === t.a.team ? t.a : t.b)).filter(Boolean);
  (B.r32 || []).forEach(t => { note(t.a); note(t.b); });
  Object.values(R).forEach(rd => (rd || []).forEach(t => { note(t.a); note(t.b); }));
  const champCard = (() => { const f = R.sf ? winners(R.sf) : [];
    if (f.length === 2) return (oddsOf[f[0].team] ?? -1) >= (oddsOf[f[1].team] ?? -1) ? f[0] : f[1];
    return B.champion || (ranked[0] && { team: ranked[0] }) || {}; })();
  const champ = champCard && champCard.team;

  const STAGES = [
    { key: 'GROUP', label: 'Group stage', cards: groups.flatMap(g => g.teams) },
    { key: 'R32', label: 'Round of 32', cards: both(B.r32) },
    { key: 'R16', label: 'Round of 16', cards: winners(B.r32) },
    { key: 'QF', label: 'Quarter-finals', cards: winners(R.r16).length ? winners(R.r16) : both(R.qf) },
    { key: 'SF', label: 'Semi-finals', cards: both(R.sf) },
    { key: 'FINAL', label: 'Final', cards: both(R.final) },
    { key: 'CHAMP', label: 'Champion', cards: [champCard] },
  ].filter(s => s.cards.length);

  const oddsScale = team => Math.max(0.9, Math.min(1.18, 0.92 + (oddsOf[team] || 0) * 2.5));
  const reachProb = (team, key) => { const r = ROAD[team] || {};
    if (key === 'R32' || key === 'R16') return ADV[team] ?? 0.2;
    if (key === 'QF') return r.pq ?? 0.1; if (key === 'SF') return r.ps ?? 0.06;
    if (key === 'FINAL') return r.pf ?? 0.04; if (key === 'CHAMP') return r.pw ?? 0.02; return 0.1; };

  // ---- renderer / scene ----
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;outline:none;touch-action:none';
  canvas.setAttribute('tabindex', '0'); canvas.setAttribute('role', 'application');
  canvas.setAttribute('aria-label', '3D tournament cascade. Left/right arrows change stage; drag to orbit; scroll to zoom; tap a nation to open its profile.');
  mount.innerHTML = ''; mount.appendChild(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setClearColor(INK, 1);
  if ('outputEncoding' in renderer && THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;
  const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(INK, 0.0065);
  const camera = new THREE.PerspectiveCamera(55, 2, 0.1, 1000);
  scene.add(new THREE.AmbientLight(0xccd4e2, 0.95));
  const klight = new THREE.PointLight(0xffe7a8, 1.2, 800); klight.position.set(30, 70, 90); scene.add(klight);
  const maxAniso = (renderer.capabilities && renderer.capabilities.getMaxAnisotropy && renderer.capabilities.getMaxAnisotropy()) || 1;
  const loader = new THREE.TextureLoader(); loader.setCrossOrigin('anonymous');
  const disposables = [], geoCache = {};
  const planeGeo = (w, h) => geoCache[w + 'x' + h] || (geoCache[w + 'x' + h] = (g => (disposables.push(g), g))(new THREE.PlaneGeometry(w, h)));

  function isoOfTeam(team) {
    if (isoOf[team]) return isoOf[team];
    const u = flagOf[team] || ''; const m = u.match(/\/([a-z]{2}(?:-[a-z]+)?)\.svg/i);
    return m ? m[1].toLowerCase() : null;
  }
  function pngUrl(team) { const iso = isoOfTeam(team); return iso ? `https://flagcdn.com/w320/${iso}.png` : null; }

  const fbCache = {};
  function fallbackTex(team) {
    if (fbCache[team]) return fbCache[team];
    const c = document.createElement('canvas'); c.width = 160; c.height = 104;
    const g = c.getContext('2d'); g.fillStyle = ccOf[team] || '#3a3630'; g.fillRect(0, 0, 160, 104);
    g.fillStyle = 'rgba(0,0,0,.32)'; g.fillRect(0, 72, 160, 32);
    g.fillStyle = '#f0e2c2'; g.font = 'bold 26px Arial'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText((isoOfTeam(team) || team.slice(0, 3)).toUpperCase(), 80, 88);
    g.strokeStyle = 'rgba(227,165,18,.85)'; g.lineWidth = 6; g.strokeRect(3, 3, 154, 98);
    const t = new THREE.CanvasTexture(c);
    if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
    disposables.push(t); fbCache[team] = t; return t;
  }

  // One real flag texture per nation, shared across every stage it appears in.
  const texByTeam = {}, pendingMats = {};
  function flagMat(card) {
    const team = card.team;
    const m = new THREE.MeshBasicMaterial({ map: texByTeam[team] || fallbackTex(team), side: THREE.DoubleSide, transparent: true });
    disposables.push(m);
    if (texByTeam[team]) return m;                 // cache hit — done
    const url = pngUrl(team);
    if (!url) return m;
    if (pendingMats[team]) { pendingMats[team].push(m); return m; }   // load already in flight
    pendingMats[team] = [m];
    loader.load(url, t => {
      if (!t.image || !t.image.width || !t.image.height) { pendingMats[team] = null; return; }
      if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
      t.anisotropy = maxAniso; t.minFilter = THREE.LinearMipmapLinearFilter; t.needsUpdate = true;
      disposables.push(t); texByTeam[team] = t;
      (pendingMats[team] || []).forEach(mat => { mat.map = t; mat.needsUpdate = true; });
      pendingMats[team] = null; requestRender();
    }, undefined, () => { pendingMats[team] = null; /* keep coloured fallback */ });
    return m;
  }
  const setScale = (mesh, mult) => { const b = mesh.userData.baseScale || 1; mesh.scale.set(b * mult, b * mult, 1); };

  const DEPTH = 48, tiles = [], stageFlags = [], nodePos = STAGES.map(() => ({}));
  function stageGrid(n) { const cols = Math.min(8, Math.max(1, n)), rows = Math.ceil(n / cols);
    const big = n <= 4, w = big ? 6.4 : 5, h = big ? 4 : 3.1; return { cols, rows, w, h, gx: w + 1.6, gy: h + 1.6 }; }
  STAGES.forEach((st, s) => {
    const arr = []; stageFlags.push(arr);
    const n = st.cards.length, G = stageGrid(n), zB = -s * DEPTH;
    const sx = -(G.cols - 1) * G.gx / 2, sy = 9 + (G.rows - 1) * G.gy / 2;
    st.cards.forEach((card, j) => {
      const col = j % G.cols, row = Math.floor(j / G.cols);
      const mesh = new THREE.Mesh(planeGeo(G.w, G.h), flagMat(card));
      mesh.position.set(sx + col * G.gx, sy - row * G.gy, zB);
      const bsc = oddsScale(card.team); mesh.scale.set(bsc, bsc, 1);
      mesh.userData = { team: card.team, stage: s, baseScale: bsc };
      scene.add(mesh); tiles.push(mesh); arr.push(mesh);
      nodePos[s][card.team] = mesh.position.clone();
    });
  });

  // ---- Sankey ribbons (one merged geometry; width ∝ reach probability) ----
  let ribbons = null;
  (function buildRibbons() {
    const pos = [], col = [], up = new THREE.Vector3(0, 1, 0), d = new THREE.Vector3(), p = new THREE.Vector3();
    const gold = [0.95, 0.76, 0.23];
    function quad(A, Bv, wdt, c) {
      d.copy(Bv).sub(A); p.crossVectors(d, up).normalize().multiplyScalar(Math.max(0.06, wdt) / 2);
      const a1 = [A.x - p.x, A.y - p.y, A.z - p.z], a2 = [A.x + p.x, A.y + p.y, A.z + p.z],
            b2 = [Bv.x + p.x, Bv.y + p.y, Bv.z + p.z], b1 = [Bv.x - p.x, Bv.y - p.y, Bv.z - p.z];
      pos.push(...a1, ...a2, ...b2, ...a1, ...b2, ...b1); for (let i = 0; i < 6; i++) col.push(...c);
    }
    for (let s = 0; s < STAGES.length - 1; s++) {
      const key = STAGES[s + 1].key;
      for (const t of Object.keys(nodePos[s])) {
        if (!nodePos[s + 1][t]) continue;
        const isCh = champ && t === champ, w = Math.max(0.12, reachProb(t, key) * 7);
        const c = isCh ? gold : hexToRgb(ccOf[t]).map(v => v * 0.7);
        quad(nodePos[s][t], nodePos[s + 1][t], isCh ? Math.max(w, 0.7) : w, c);
      }
    }
    if (!pos.length) return;
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute('color', new THREE.Float32BufferAttribute(col, 3)); disposables.push(g);
    const m = new THREE.MeshBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false });
    disposables.push(m); ribbons = new THREE.Mesh(g, m); scene.add(ribbons);
  })();

  // ---- constrained-orbit camera (target a stage; orbit + zoom only) ----
  let cs = 0, mode = 'pred', picked = null;
  const target = new THREE.Vector3(0, 9, 0), targetT = new THREE.Vector3(0, 9, 0);
  let dist = 60, distT = 48, yaw = 0, yawT = 0, pitch = 0.14, pitchT = 0.14;
  const YAW_LIM = 1.15, PITCH_MIN = -0.12, PITCH_MAX = 0.92, DIST_MIN = 18, DIST_MAX = 150;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function focusStage(i) {
    cs = clamp(i, 0, STAGES.length - 1);
    const n = STAGES[cs].cards.length, G = stageGrid(n);
    const spanX = (G.cols - 1) * G.gx + G.w, spanY = (G.rows - 1) * G.gy + G.h;
    targetT.set(0, 9, -cs * DEPTH);
    distT = clamp(Math.max(spanX * 0.62, spanY * 1.05) + 16, DIST_MIN, DIST_MAX);
    yawT = 0; pitchT = 0.14;
    if (picked && picked.userData.stage !== cs) { setScale(picked, 1); picked = null; }
    tiles.forEach(f => f.material.opacity = f.userData.stage === cs ? 1 : 0.22);
    if (ui.title) ui.title.textContent = STAGES[cs].label + ' · ' + STAGES[cs].cards.length;
    [...ui.rail.children].forEach((b, k) => b.classList.toggle('on', k === cs));
    requestRender();
  }

  const ui = buildUI(mount);
  ui.rail.innerHTML = '';
  STAGES.forEach((st, i) => { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = st.key;
    b.title = st.label; b.setAttribute('aria-label', st.label); b.onclick = () => focusStage(i); ui.rail.appendChild(b); });
  ui.prev.onclick = () => focusStage(cs - 1); ui.next.onclick = () => focusStage(cs + 1);
  ui.pred.onclick = () => setMode('pred'); ui.real.onclick = () => setMode('real');
  function setMode(m) { mode = m; ui.pred.classList.toggle('on', m === 'pred'); ui.real.classList.toggle('on', m === 'real');
    if (ribbons) ribbons.material.opacity = m === 'pred' ? 0.85 : 0.14; requestRender(); }

  // ---- interaction: pointer-based orbit (1 finger) + pinch zoom (2 fingers) ----
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const ptrs = new Map(); let moved = 0, lastPinch = 0;
  function avg() { let x = 0, y = 0; ptrs.forEach(p => { x += p.x; y += p.y; }); const n = ptrs.size || 1; return { x: x / n, y: y / n }; }
  function pinchDist() { const a = [...ptrs.values()]; if (a.length < 2) return 0; return Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); }
  const onDown = e => { canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); moved = 0; lastPinch = pinchDist(); canvas.style.cursor = 'grabbing'; requestRender(); };
  const onMove = e => {
    if (!ptrs.has(e.pointerId)) return;
    const prev = avg(); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); const now = avg();
    if (ptrs.size >= 2) { const pd = pinchDist(); if (lastPinch) distT = clamp(distT * (lastPinch / (pd || lastPinch)), DIST_MIN, DIST_MAX); lastPinch = pd; requestRender(); return; }
    const dx = now.x - prev.x, dy = now.y - prev.y; moved += Math.abs(dx) + Math.abs(dy);
    yawT = clamp(yawT + dx * 0.005, -YAW_LIM, YAW_LIM);
    pitchT = clamp(pitchT - dy * 0.004, PITCH_MIN, PITCH_MAX); requestRender();
  };
  const onUp = e => {
    const wasTap = ptrs.size === 1 && moved < 7;
    ptrs.delete(e.pointerId); lastPinch = pinchDist(); if (!ptrs.size) canvas.style.cursor = 'grab';
    if (wasTap) { const r = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1; mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(stageFlags[cs] || [])[0];
      if (hit) { if (picked) setScale(picked, 1); picked = hit.object; setScale(picked, 1.35);
        if (onPick) onPick(picked.userData.team, canvas); requestRender(); } }
  };
  const onWheel = e => { e.preventDefault(); distT = clamp(distT + e.deltaY * 0.05, DIST_MIN, DIST_MAX); requestRender(); };
  const onKeyDown = e => { const k = e.key.toLowerCase();
    if (k === 'arrowright' || k === 'd') { e.preventDefault(); return focusStage(cs + 1); }
    if (k === 'arrowleft' || k === 'a') { e.preventDefault(); return focusStage(cs - 1); }
    if (k === '+' || k === '=') { distT = clamp(distT - 8, DIST_MIN, DIST_MAX); requestRender(); }
    if (k === '-' || k === '_') { distT = clamp(distT + 8, DIST_MIN, DIST_MAX); requestRender(); } };
  const onResize = () => { const w = mount.clientWidth || 800, h = mount.clientHeight || 500;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix(); requestRender(); };
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup', onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('resize', onResize);

  // ---- render-on-demand loop (pauses when settled / offscreen / tab hidden) ----
  let raf = 0, alive = true, firstFrame = true, rendering = false, onScreen = true, tabOn = true;
  const visible = () => onScreen && tabOn;
  function settled() {
    return ptrs.size === 0 && Math.abs(dist - distT) < 0.05 && Math.abs(yaw - yawT) < 0.0015
      && Math.abs(pitch - pitchT) < 0.0015 && target.distanceToSquared(targetT) < 0.01;
  }
  function frame() {
    if (!alive) { rendering = false; return; }
    target.lerp(targetT, 0.1); dist += (distT - dist) * 0.1; yaw += (yawT - yaw) * 0.12; pitch += (pitchT - pitch) * 0.12;
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    camera.position.set(target.x + dist * Math.sin(yaw) * cp, target.y + dist * sp, target.z + dist * Math.cos(yaw) * cp);
    camera.lookAt(target);
    try { renderer.render(scene, camera); }
    catch (err) { alive = false; rendering = false; if (hooks && hooks.onError) hooks.onError(err); return; }
    if (firstFrame) { firstFrame = false; if (hooks && hooks.onReady) hooks.onReady(); }
    if (visible() && !settled()) { raf = requestAnimationFrame(frame); } else { rendering = false; }
  }
  function requestRender() { if (alive && visible() && !rendering) { rendering = true; raf = requestAnimationFrame(frame); } }

  function setOnScreen(v) { onScreen = v; if (v) requestRender(); }
  let io = null;
  try { io = new IntersectionObserver(es => setOnScreen(!!es[0] && es[0].isIntersecting), { threshold: 0.01 }); io.observe(mount); }
  catch (e) { /* no IO — always considered on-screen */ }
  const onVis = () => { tabOn = !document.hidden; if (tabOn) requestRender(); };
  document.addEventListener('visibilitychange', onVis);

  onResize(); focusStage(0); setMode('pred'); requestRender();

  return { destroy() {
    alive = false; cancelAnimationFrame(raf);
    canvas.removeEventListener('pointerdown', onDown); canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('pointerup', onUp); canvas.removeEventListener('pointercancel', onUp);
    canvas.removeEventListener('wheel', onWheel);
    window.removeEventListener('keydown', onKeyDown); window.removeEventListener('resize', onResize);
    document.removeEventListener('visibilitychange', onVis);
    if (io) { try { io.disconnect(); } catch (e) {} }
    disposables.forEach(d => { try { d.dispose && d.dispose(); } catch (e) {} });
    try { renderer.dispose(); } catch (e) {}
    mount.innerHTML = '';
  } };
}

function buildUI(mount) {
  if (getComputedStyle(mount).position === 'static') mount.style.position = 'relative';
  const base = 'position:absolute;font-family:inherit;z-index:2;';
  const title = el('div', base + 'left:14px;top:12px;font-size:15px;color:#fff;text-shadow:0 1px 4px rgba(0,0,0,.6);');
  const hint = el('div', base + 'left:14px;bottom:52px;font-size:11px;color:#cdbf9f;opacity:.8;text-shadow:0 1px 3px rgba(0,0,0,.7);');
  hint.textContent = 'drag to orbit · scroll / pinch to zoom · tap a flag';
  const modes = el('div', base + 'left:50%;top:12px;transform:translateX(-50%);display:inline-flex;background:rgba(20,16,10,.82);border:1px solid #3a3630;border-radius:9px;overflow:hidden;');
  const pred = btn('Prediction'), real = btn('Reality'); modes.append(pred, real);
  const bar = el('div', base + 'left:0;right:0;bottom:11px;display:flex;justify-content:center;gap:6px;flex-wrap:wrap;padding:0 10px;');
  const prev = btn('‹'), rail = el('div', 'display:flex;gap:5px;flex-wrap:wrap;justify-content:center;'), next = btn('›');
  prev.setAttribute('aria-label', 'Previous stage'); next.setAttribute('aria-label', 'Next stage');
  bar.append(prev, rail, next);
  const style = document.createElement('style');
  style.textContent = '.o3d-btn{cursor:pointer;border:1px solid #3a3630;border-radius:8px;padding:7px 11px;font-size:12px;background:#1c1a17;color:#cdbf9f;font-family:inherit;min-width:34px}.o3d-btn:hover{border-color:#e3a512;color:#f0e2c2}.o3d-btn.on{background:#e3a512;color:#1c1407;border-color:#e3a512}';
  mount.append(style, title, hint, modes, bar);
  return { title, rail, prev, next, pred, real };
  function el(tag, s) { const e = document.createElement(tag); e.style.cssText = s; return e; }
  function btn(t) { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = t; return b; }
}
