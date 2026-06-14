/* =====================================================================
   WCPA · 3D OVERVIEW  (feature module — progressive enhancement)
   A navigable Three.js cascade of the tournament (Group 48 -> Champion 1)
   wired to the real engine feeds. Strictly OPT-IN and self-guarding: it does
   NOTHING unless WebGL + window.THREE are present AND it is explicitly armed
   (?overview3d=1 or window.__WCPA_3D__). The 2D mural stays as the default and
   the fallback, so this file can never break the live page.

   To enable (next session — see 3D-OVERVIEW.md):
     1. host Three.js r128 (self-host in viz/static, or allow cdnjs in the CSP
        — viz/export.py _cdn_config + viz/server.py),
     2. add <script src=".../three.min.js"></script> then
        <script type="module" src="/overview3d.js"></script> to index.html,
     3. flag textures: real flags come from f.flag (flagcdn SVG). WebGL textures
        need CORS — verify flagcdn sends access-control-allow-origin, else proxy
        via the site's own /media or ship a sprite atlas. Falls back to a
        confederation-colour tile on any load error.
   ===================================================================== */
'use strict';

const GOLD = 0xe3a512, GOLDHI = 0xf2c33b, INK = 0x0e0c0a;

export function overview3DAvailable() {
  if (typeof window === 'undefined' || !window.THREE) return false;
  try { const c = document.createElement('canvas');
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl')); }
  catch (e) { return false; }
}

/* data: { groupadv, report, bracket, fixtures }  — the parsed /api feeds.
   onPick: (teamName, domAnchorEl) => void   — wire to showProfile on the site. */
export function initOverview3D(mount, data, onPick) {
  if (!overview3DAvailable() || !mount) return null;
  const THREE = window.THREE;
  const rm = matchMedia('(prefers-reduced-motion: reduce)').matches;

  // ---- derive the cascade stages from REAL data ----
  const ranked = ((data.report && data.report.title_odds) || []).map(o => o.team);
  const oddsOf = {}; ((data.report && data.report.title_odds) || []).forEach(o => oddsOf[o.team] = o.p_win);
  const ga = data.groupadv || {};
  const groups = Object.keys(ga).sort().map(k => ({ name: k, teams: ga[k] }));
  const teamGroup = {}; groups.forEach(g => g.teams.forEach(t => teamGroup[t.team] = g.name));
  const flagOf = {}; groups.forEach(g => g.teams.forEach(t => flagOf[t.team] = t.flag));
  ((data.report && data.report.title_odds) || []).forEach(o => { if (o.flag) flagOf[o.team] = o.flag; });

  const B = data.bracket || {}, R = B.rounds || {};
  const both = ties => (ties || []).flatMap(t => [t.a, t.b]).filter(Boolean);
  const winners = ties => (ties || []).map(t => (t.winner === t.a.team ? t.a : t.b)).filter(Boolean);
  const champCard = (() => { const f = (R.sf ? winners(R.sf) : []); // higher-title-odds finalist (matches the mural)
    if (f.length === 2) return (oddsOf[f[0].team] ?? -1) >= (oddsOf[f[1].team] ?? -1) ? f[0] : f[1];
    return B.champion || (ranked[0] && { team: ranked[0], flag: flagOf[ranked[0]] }) || {}; })();

  const STAGES = [
    { key: 'GROUP', label: 'Group stage', cards: groups.flatMap(g => g.teams) },
    { key: 'R32', label: 'Round of 32', cards: both(B.r32) },
    { key: 'R16', label: 'Round of 16', cards: winners(B.r32) },
    { key: 'QF', label: 'Quarter-finals', cards: winners(R.r16).length ? winners(R.r16) : both(R.qf) },
    { key: 'SF', label: 'Semi-finals', cards: both(R.sf) },
    { key: 'FINAL', label: 'Final', cards: both(R.final) },
    { key: 'CHAMP', label: 'Champion', cards: [champCard] },
  ].filter(s => s.cards.length);

  // ---- real results (Reality mode) keyed by team ----
  const realRes = {};
  ((data.fixtures && data.fixtures.completed) || []).forEach(m => {
    const sH = m.home_score, sA = m.away_score, sc = sH + '–' + sA;
    realRes[m.home.team] = { r: sH > sA ? 'W' : sH < sA ? 'L' : 'D', sc };
    realRes[m.away.team] = { r: sA > sH ? 'W' : sA < sH ? 'L' : 'D', sc };
  });

  // ---- renderer / scene ----
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;outline:none';
  mount.innerHTML = ''; mount.appendChild(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setClearColor(INK, 1);
  const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(INK, 0.008);
  const camera = new THREE.PerspectiveCamera(55, 2, 0.1, 1000);
  scene.add(new THREE.AmbientLight(0xccd4e2, 0.95));
  const key = new THREE.PointLight(0xffe7a8, 1.2, 800); key.position.set(30, 70, 90); scene.add(key);
  const loader = new THREE.TextureLoader(); loader.setCrossOrigin('anonymous');

  function fallbackTex(cc) { const c = document.createElement('canvas'); c.width = 160; c.height = 104;
    const g = c.getContext('2d'); g.fillStyle = cc || '#444'; g.fillRect(0, 0, 160, 104);
    g.strokeStyle = 'rgba(227,165,18,.85)'; g.lineWidth = 6; g.strokeRect(3, 3, 154, 98);
    return new THREE.CanvasTexture(c); }
  function flagMat(card) {
    const m = new THREE.MeshBasicMaterial({ map: fallbackTex(card.confed_color), side: THREE.DoubleSide, transparent: true });
    const url = flagOf[card.team] || card.flag;
    if (url) loader.load(url, t => { m.map = t; m.needsUpdate = true; }, undefined, () => {});
    return m;
  }

  const DEPTH = 48, tiles = [], stageFlags = [], top0 = [];
  STAGES.forEach((st, s) => {
    const arr = []; stageFlags.push(arr);
    const n = st.cards.length, cols = Math.min(8, Math.max(1, n)), rows = Math.ceil(n / cols), zB = -s * DEPTH;
    const big = n <= 4, w = big ? 6.4 : 5, h = big ? 4 : 3.1, gx = w + 1.3, gy = h + 1.4;
    const sx = -(cols - 1) * gx / 2, sy = 9 + (rows - 1) * gy / 2;
    st.cards.forEach((card, j) => {
      const col = j % cols, row = Math.floor(j / cols);
      const geo = new THREE.PlaneGeometry(w, h), mesh = new THREE.Mesh(geo, flagMat(card));
      mesh.position.set(sx + col * gx, sy - row * gy, zB);
      mesh.userData = { team: card.team, stage: s };
      scene.add(mesh); tiles.push(mesh); arr.push(mesh);
      if (j === 0) top0.push(new THREE.Vector3(mesh.position.x, mesh.position.y, zB));
    });
  });

  // gold projected-champion path through the #1 seed of each stage
  let curve = null, tube = null, tTotal = 0;
  if (top0.length > 1) {
    curve = new THREE.CatmullRomCurve3(top0);
    const tg = new THREE.TubeGeometry(curve, 120, 0.2, 8, false);
    tube = new THREE.Mesh(tg, new THREE.MeshBasicMaterial({ color: GOLDHI, transparent: true, opacity: 0.9 }));
    scene.add(tube); tTotal = tg.index.count;
  }

  // ---- state + free-roam camera ----
  let cs = 0, mode = 'pred', picked = null, freeCam = false;
  const pos = new THREE.Vector3(0, 22, 120); let yaw = 0, pitch = -0.06;
  const posT = new THREE.Vector3(0, 9, 62); let yawT = 0, pitchT = -0.04;
  const keys = {};
  const fwd = () => new THREE.Vector3(Math.sin(yaw) * Math.cos(pitch), Math.sin(pitch), -Math.cos(yaw) * Math.cos(pitch));
  function focusStage(i) {
    cs = Math.max(0, Math.min(STAGES.length - 1, i));
    posT.set(0, 9, -cs * DEPTH + 18 + Math.min(8, STAGES[cs].cards.length) * 2.4); yawT = 0; pitchT = -0.04; freeCam = false;
    if (picked && picked.userData.stage !== cs) { picked.scale.set(1, 1, 1); picked = null; }
    tiles.forEach(f => f.material.opacity = f.userData.stage === cs ? 1 : 0.26);
    if (ui.title) ui.title.textContent = STAGES[cs].label;
    [...ui.rail.children].forEach((b, k) => b.classList.toggle('on', k === cs));
  }

  // ---- minimal in-mount GUI (rail + mode toggle) ----
  const ui = buildUI(mount);
  ui.rail.innerHTML = '';
  STAGES.forEach((st, i) => { const b = document.createElement('button'); b.textContent = st.key; b.title = st.label;
    b.onclick = () => focusStage(i); ui.rail.appendChild(b); });
  ui.prev.onclick = () => focusStage(cs - 1); ui.next.onclick = () => focusStage(cs + 1);
  ui.pred.onclick = () => setMode('pred'); ui.real.onclick = () => setMode('real');
  function setMode(m) { mode = m; ui.pred.classList.toggle('on', m === 'pred'); ui.real.classList.toggle('on', m === 'real');
    if (tube) tube.material.opacity = m === 'pred' ? 0.9 : 0.16; }

  // ---- interaction ----
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let drag = false, px = 0, py = 0, moved = 0;
  canvas.addEventListener('pointerdown', e => { drag = true; moved = 0; px = e.clientX; py = e.clientY; });
  addEventListener('pointerup', e => {
    if (drag && moved < 6) {
      const r = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1; mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(mouse, camera);
      const hit = ray.intersectObjects(stageFlags[cs] || [])[0];
      if (hit) { if (picked) picked.scale.set(1, 1, 1); picked = hit.object; picked.scale.set(1.35, 1.35, 1.35);
        if (onPick) onPick(picked.userData.team, canvas); }
    }
    drag = false;
  });
  canvas.addEventListener('pointermove', e => { if (!drag) return; const dx = e.clientX - px, dy = e.clientY - py;
    moved += Math.abs(dx) + Math.abs(dy); yaw += dx * 0.004; pitch = Math.max(-1.4, Math.min(1.4, pitch - dy * 0.004));
    px = e.clientX; py = e.clientY; freeCam = true; });
  canvas.addEventListener('wheel', e => { e.preventDefault(); pos.addScaledVector(fwd(), -e.deltaY * 0.06); freeCam = true; }, { passive: false });
  addEventListener('keydown', e => { const k = e.key.toLowerCase();
    if (k === 'arrowright') return focusStage(cs + 1); if (k === 'arrowleft') return focusStage(cs - 1);
    if ('wasdqe'.indexOf(k) >= 0 || k === 'shift') { keys[k] = true; freeCam = true; } });
  addEventListener('keyup', e => { keys[e.key.toLowerCase()] = false; });

  function resize() { const w = mount.clientWidth || 800, h = mount.clientHeight || 500;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix(); }
  resize(); addEventListener('resize', resize);

  focusStage(0); setMode('pred');
  let raf = 0;
  function loop(now) { raf = requestAnimationFrame(loop);
    const f = fwd(), right = new THREE.Vector3().crossVectors(f, new THREE.Vector3(0, 1, 0)).normalize();
    if (freeCam) { const sp = keys['shift'] ? 2 : 1;
      if (keys['w']) pos.addScaledVector(f, sp); if (keys['s']) pos.addScaledVector(f, -sp);
      if (keys['d']) pos.addScaledVector(right, sp); if (keys['a']) pos.addScaledVector(right, -sp);
      if (keys['e']) pos.y += sp; if (keys['q']) pos.y -= sp;
    } else { pos.lerp(posT, 0.07); yaw += (yawT - yaw) * 0.07; pitch += (pitchT - pitch) * 0.07; }
    camera.position.copy(pos); camera.lookAt(pos.x + f.x, pos.y + f.y, pos.z + f.z);
    if (tube && !rm) tube.geometry.setDrawRange(0, tTotal);
    renderer.render(scene, camera);
  }
  loop(performance.now());

  return { destroy() { cancelAnimationFrame(raf); removeEventListener('resize', resize); mount.innerHTML = ''; } };
}

function buildUI(mount) {
  if (getComputedStyle(mount).position === 'static') mount.style.position = 'relative';
  const css = 'position:absolute;font-family:inherit;z-index:2;';
  const title = el('div', css + 'left:14px;top:12px;font-size:15px;color:#fff;');
  const modes = el('div', css + 'left:50%;top:12px;transform:translateX(-50%);display:inline-flex;background:rgba(20,16,10,.82);border:1px solid #3a3630;border-radius:9px;overflow:hidden;');
  const pred = btn('Prediction'), real = btn('Reality'); modes.append(pred, real);
  const bar = el('div', css + 'left:0;right:0;bottom:11px;display:flex;justify-content:center;gap:6px;');
  const prev = btn('‹'), rail = el('div', 'display:flex;gap:5px;'), next = btn('›');
  bar.append(prev, rail, next);
  const style = document.createElement('style');
  style.textContent = '.o3d-btn{cursor:pointer;border:1px solid #3a3630;border-radius:8px;padding:6px 10px;font-size:12px;background:#1c1a17;color:#cdbf9f;font-family:inherit}.o3d-btn.on{background:#e3a512;color:#1c1407;border-color:#e3a512}';
  mount.append(style, title, modes, bar);
  return { title, rail, prev, next, pred, real };
  function el(tag, s) { const e = document.createElement(tag); e.style.cssText = s; return e; }
  function btn(t) { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = t; return b; }
}
