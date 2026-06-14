/* =====================================================================
   WCPA · 3D OVERVIEW  (feature module — progressive enhancement)
   A navigable Three.js cascade of the tournament (Group 48 -> Champion 1)
   wired to the real engine feeds. Self-guarding: does NOTHING unless WebGL +
   window.THREE are present. Mounted into a dedicated container by a visible
   2D<->3D toggle (app.js); the 2D mural stays intact as the fallback, and
   destroy() fully tears down (listeners + GPU resources) so the toggle is clean.

   Enable (see 3D-OVERVIEW.md): host three.min.js r128 same-origin in viz/static.
   Flag textures load from f.flag (flagcdn); WebGL needs CORS — falls back to a
   confederation-colour tile with the country code on any load/CORS error.
   ===================================================================== */
'use strict';

const GOLD = 0xe3a512, GOLDHI = 0xf2c33b, INK = 0x0e0c0a;

export function overview3DAvailable() {
  if (typeof window === 'undefined' || !window.THREE) return false;
  try { const c = document.createElement('canvas');
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl')); }
  catch (e) { return false; }
}

export function initOverview3D(mount, data, onPick) {
  if (!overview3DAvailable() || !mount) return null;
  const THREE = window.THREE;

  // ---- derive cascade stages from REAL feeds ----
  const ranked = ((data.report && data.report.title_odds) || []).map(o => o.team);
  const oddsOf = {}; ((data.report && data.report.title_odds) || []).forEach(o => oddsOf[o.team] = o.p_win);
  const ga = data.groupadv || {};
  const groups = Object.keys(ga).sort().map(k => ({ name: k, teams: ga[k] }));
  const flagOf = {}, isoOf = {}, ccOf = {};
  const note = c => { if (!c || !c.team) return; if (c.flag) flagOf[c.team] = c.flag;
    if (c.iso2) isoOf[c.team] = c.iso2; if (c.confed_color) ccOf[c.team] = c.confed_color; };
  groups.forEach(g => g.teams.forEach(note));
  ((data.report && data.report.title_odds) || []).forEach(note);

  const B = data.bracket || {}, R = B.rounds || {};
  const both = ties => (ties || []).flatMap(t => [t.a, t.b]).filter(Boolean);
  const winners = ties => (ties || []).map(t => (t.winner === t.a.team ? t.a : t.b)).filter(Boolean);
  (B.r32 || []).forEach(t => { note(t.a); note(t.b); });
  Object.values(R).forEach(rd => (rd || []).forEach(t => { note(t.a); note(t.b); }));
  const champCard = (() => { const f = R.sf ? winners(R.sf) : [];
    if (f.length === 2) return (oddsOf[f[0].team] ?? -1) >= (oddsOf[f[1].team] ?? -1) ? f[0] : f[1];
    return B.champion || (ranked[0] && { team: ranked[0] }) || {}; })();

  const STAGES = [
    { key: 'GROUP', label: 'Group stage', cards: groups.flatMap(g => g.teams) },
    { key: 'R32', label: 'Round of 32', cards: both(B.r32) },
    { key: 'R16', label: 'Round of 16', cards: winners(B.r32) },
    { key: 'QF', label: 'Quarter-finals', cards: winners(R.r16).length ? winners(R.r16) : both(R.qf) },
    { key: 'SF', label: 'Semi-finals', cards: both(R.sf) },
    { key: 'FINAL', label: 'Final', cards: both(R.final) },
    { key: 'CHAMP', label: 'Champion', cards: [champCard] },
  ].filter(s => s.cards.length);

  // ---- renderer / scene ----
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;outline:none';
  mount.innerHTML = ''; mount.appendChild(canvas);
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setClearColor(INK, 1);
  const scene = new THREE.Scene(); scene.fog = new THREE.FogExp2(INK, 0.008);
  const camera = new THREE.PerspectiveCamera(55, 2, 0.1, 1000);
  scene.add(new THREE.AmbientLight(0xccd4e2, 0.95));
  const klight = new THREE.PointLight(0xffe7a8, 1.2, 800); klight.position.set(30, 70, 90); scene.add(klight);
  const loader = new THREE.TextureLoader(); loader.setCrossOrigin('anonymous');
  const disposables = [];

  function fallbackTex(team) {
    const c = document.createElement('canvas'); c.width = 160; c.height = 104;
    const g = c.getContext('2d'); g.fillStyle = ccOf[team] || '#3a3630'; g.fillRect(0, 0, 160, 104);
    g.fillStyle = 'rgba(0,0,0,.32)'; g.fillRect(0, 72, 160, 32);
    g.fillStyle = '#f0e2c2'; g.font = 'bold 26px Arial'; g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText((isoOf[team] || team.slice(0, 3)).toUpperCase(), 80, 88);
    g.strokeStyle = 'rgba(227,165,18,.85)'; g.lineWidth = 6; g.strokeRect(3, 3, 154, 98);
    const t = new THREE.CanvasTexture(c); disposables.push(t); return t;
  }
  function flagMat(card) {
    const m = new THREE.MeshBasicMaterial({ map: fallbackTex(card.team), side: THREE.DoubleSide, transparent: true });
    const url = flagOf[card.team];
    if (url) loader.load(url, t => { m.map = t; m.needsUpdate = true; disposables.push(t); }, undefined, () => {});
    disposables.push(m); return m;
  }

  const DEPTH = 48, tiles = [], stageFlags = [], top0 = [];
  STAGES.forEach((st, s) => {
    const arr = []; stageFlags.push(arr);
    const n = st.cards.length, cols = Math.min(8, Math.max(1, n)), rows = Math.ceil(n / cols), zB = -s * DEPTH;
    const big = n <= 4, w = big ? 6.4 : 5, h = big ? 4 : 3.1, gx = w + 1.3, gy = h + 1.4;
    const sx = -(cols - 1) * gx / 2, sy = 9 + (rows - 1) * gy / 2;
    st.cards.forEach((card, j) => {
      const col = j % cols, row = Math.floor(j / cols);
      const geo = new THREE.PlaneGeometry(w, h); disposables.push(geo);
      const mesh = new THREE.Mesh(geo, flagMat(card));
      mesh.position.set(sx + col * gx, sy - row * gy, zB);
      mesh.userData = { team: card.team, stage: s };
      scene.add(mesh); tiles.push(mesh); arr.push(mesh);
      if (j === 0) top0.push(new THREE.Vector3(mesh.position.x, mesh.position.y, zB));
    });
  });

  let curve = null, tube = null;
  if (top0.length > 1) {
    curve = new THREE.CatmullRomCurve3(top0);
    const tg = new THREE.TubeGeometry(curve, 120, 0.2, 8, false); disposables.push(tg);
    const tm = new THREE.MeshBasicMaterial({ color: GOLDHI, transparent: true, opacity: 0.9 }); disposables.push(tm);
    tube = new THREE.Mesh(tg, tm); scene.add(tube);
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

  const ui = buildUI(mount);
  ui.rail.innerHTML = '';
  STAGES.forEach((st, i) => { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = st.key;
    b.title = st.label; b.onclick = () => focusStage(i); ui.rail.appendChild(b); });
  ui.prev.onclick = () => focusStage(cs - 1); ui.next.onclick = () => focusStage(cs + 1);
  ui.pred.onclick = () => setMode('pred'); ui.real.onclick = () => setMode('real');
  function setMode(m) { mode = m; ui.pred.classList.toggle('on', m === 'pred'); ui.real.classList.toggle('on', m === 'real');
    if (tube) tube.material.opacity = m === 'pred' ? 0.9 : 0.16; }

  // ---- interaction (removable listeners) ----
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  let drag = false, px = 0, py = 0, moved = 0;
  const onDown = e => { drag = true; moved = 0; px = e.clientX; py = e.clientY; };
  const onMove = e => { if (!drag) return; const dx = e.clientX - px, dy = e.clientY - py;
    moved += Math.abs(dx) + Math.abs(dy); yaw += dx * 0.004; pitch = Math.max(-1.4, Math.min(1.4, pitch - dy * 0.004));
    px = e.clientX; py = e.clientY; freeCam = true; };
  const onUp = e => { if (drag && moved < 6) { const r = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1; mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
      ray.setFromCamera(mouse, camera); const hit = ray.intersectObjects(stageFlags[cs] || [])[0];
      if (hit) { if (picked) picked.scale.set(1, 1, 1); picked = hit.object; picked.scale.set(1.35, 1.35, 1.35);
        if (onPick) onPick(picked.userData.team, canvas); } } drag = false; };
  const onWheel = e => { e.preventDefault(); pos.addScaledVector(fwd(), -e.deltaY * 0.06); freeCam = true; };
  const onKeyDown = e => { const k = e.key.toLowerCase();
    if (k === 'arrowright') return focusStage(cs + 1); if (k === 'arrowleft') return focusStage(cs - 1);
    if ('wasdqe'.indexOf(k) >= 0 || k === 'shift') { keys[k] = true; freeCam = true; } };
  const onKeyUp = e => { keys[e.key.toLowerCase()] = false; };
  const onResize = () => { const w = mount.clientWidth || 800, h = mount.clientHeight || 500;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.setSize(w, h, false);
    camera.aspect = w / h; camera.updateProjectionMatrix(); };
  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('pointerup', onUp);
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('keyup', onKeyUp);
  window.addEventListener('resize', onResize);

  onResize(); focusStage(0); setMode('pred');
  let raf = 0, alive = true;
  function loop() { if (!alive) return; raf = requestAnimationFrame(loop);
    const f = fwd(), right = new THREE.Vector3().crossVectors(f, new THREE.Vector3(0, 1, 0)).normalize();
    if (freeCam) { const sp = keys['shift'] ? 2 : 1;
      if (keys['w']) pos.addScaledVector(f, sp); if (keys['s']) pos.addScaledVector(f, -sp);
      if (keys['d']) pos.addScaledVector(right, sp); if (keys['a']) pos.addScaledVector(right, -sp);
      if (keys['e']) pos.y += sp; if (keys['q']) pos.y -= sp;
    } else { pos.lerp(posT, 0.07); yaw += (yawT - yaw) * 0.07; pitch += (pitchT - pitch) * 0.07; }
    camera.position.copy(pos); camera.lookAt(pos.x + f.x, pos.y + f.y, pos.z + f.z);
    renderer.render(scene, camera);
  }
  loop();

  return { destroy() {
    alive = false; cancelAnimationFrame(raf);
    canvas.removeEventListener('pointerdown', onDown); canvas.removeEventListener('pointermove', onMove);
    canvas.removeEventListener('wheel', onWheel);
    window.removeEventListener('pointerup', onUp); window.removeEventListener('keydown', onKeyDown);
    window.removeEventListener('keyup', onKeyUp); window.removeEventListener('resize', onResize);
    disposables.forEach(d => { try { d.dispose && d.dispose(); } catch (e) {} });
    try { renderer.dispose(); } catch (e) {}
    mount.innerHTML = '';
  } };
}

function buildUI(mount) {
  if (getComputedStyle(mount).position === 'static') mount.style.position = 'relative';
  const base = 'position:absolute;font-family:inherit;z-index:2;';
  const title = el('div', base + 'left:14px;top:12px;font-size:15px;color:#fff;');
  const modes = el('div', base + 'left:50%;top:12px;transform:translateX(-50%);display:inline-flex;background:rgba(20,16,10,.82);border:1px solid #3a3630;border-radius:9px;overflow:hidden;');
  const pred = btn('Prediction'), real = btn('Reality'); modes.append(pred, real);
  const bar = el('div', base + 'left:0;right:0;bottom:11px;display:flex;justify-content:center;gap:6px;');
  const prev = btn('‹'), rail = el('div', 'display:flex;gap:5px;'), next = btn('›');
  bar.append(prev, rail, next);
  const style = document.createElement('style');
  style.textContent = '.o3d-btn{cursor:pointer;border:1px solid #3a3630;border-radius:8px;padding:6px 10px;font-size:12px;background:#1c1a17;color:#cdbf9f;font-family:inherit}.o3d-btn.on{background:#e3a512;color:#1c1407;border-color:#e3a512}';
  mount.append(style, title, modes, bar);
  return { title, rail, prev, next, pred, real };
  function el(tag, s) { const e = document.createElement(tag); e.style.cssText = s; return e; }
  function btn(t) { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = t; return b; }
}
