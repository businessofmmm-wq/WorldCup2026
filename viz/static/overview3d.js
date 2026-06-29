/* =====================================================================
   WCPA · 3D KNOCKOUT BRACKET  (Three.js r128)
   Proper binary bracket tree (R32 → Final) rendered in 3D:
     • BoxGeometry panels per team slot — extruded, real depth
     • Connector arm geometry (horizontal + vertical bracket arms)
     • Per-round z-cascade: R32 is furthest back, Final is closest
     • Flag textures on the +z face of each team panel
     • Directional + point lights for realistic depth shading
     • Champion panel glows gold with emissive material
     • Constrained-orbit navigation; tap flag to open team profile
     • Render-on-demand; pauses when offscreen / tab hidden

   Bracket layout world space
     x-axis  rounds: R32=-52 … Final=+52 (STAGE_W=26 per round)
     y-axis  match positions, centred at 0 (±32 world units)
     z-axis  per-round depth cascade: R32=+12, R16=+6, QF=0, SF=-6, Final=-12
   ===================================================================== */
'use strict';

const GOLD = 0xe3a512, GOLDDP = 0xd49a16, INK = 0x0e0c0a, CREAM = 0xf0e2c2;
const TERRA = 0xd2541b, TEAL = 0x49a39d;

function hexToRgb(h) {
  h = (h || '#5a6b86').replace('#', '');
  if (h.length === 3) h = h.split('').map(x => x + x).join('');
  const n = parseInt(h, 16) || 0;
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

export function overview3DAvailable() {
  if (typeof window === 'undefined' || !window.THREE) return false;
  try {
    const c = document.createElement('canvas');
    return !!(c.getContext('webgl') || c.getContext('experimental-webgl'));
  } catch (e) { return false; }
}

// ---- Bracket tree geometry constants ----------------------------------------
const STAGE_W  = 26;   // world-unit x-spacing between rounds
const SLOT_H   = 1.75; // height of each team slot
const SLOT_GAP = 0.35; // gap between team A and team B slots
const PAN_W    = 22;   // match panel width (along x)
const PAN_D    = 1.20; // panel depth (along z, extrusion)
const ARM_H    = 0.22; // connector arm height (y)
const ARM_D    = 0.28; // connector arm depth (z)
const STRP_W   = 0.55; // team-colour stripe width on left of panel

// Per-round x-centres and z-depth (R32 furthest back → Final closest)
const ROUND_DEFS = [
  { key: 'r32',   xi: 0, zd: +12, n: 16, ySpacing: 4  },
  { key: 'r16',   xi: 1, zd:  +6, n:  8, ySpacing: 8  },
  { key: 'qf',    xi: 2, zd:   0, n:  4, ySpacing: 16 },
  { key: 'sf',    xi: 3, zd:  -6, n:  2, ySpacing: 32 },
  { key: 'final', xi: 4, zd: -12, n:  1, ySpacing: 64 },
];
// x centre of each round panel column
function roundX(xi) { return (xi - 2) * STAGE_W; }
// y centres for matches in a given round
function matchYCentres(n, ySpacing) {
  const half = (n - 1) / 2;
  return Array.from({ length: n }, (_, i) => (i - half) * ySpacing);
}

// ---- Team helpers -----------------------------------------------------------
const TEAM_COLORS = {
  'Argentina':'#75AADB','Brazil':'#009B3A','France':'#003189','England':'#FFFFFF',
  'Spain':'#AA151B','Germany':'#FFFFFF','Portugal':'#006600','Netherlands':'#FF7F00',
  'Belgium':'#ED2939','Italy':'#003399','Uruguay':'#73CDFE','Mexico':'#006847',
  'United States':'#B22234','Japan':'#BC002D','South Korea':'#003478',
  'Senegal':'#00853F','Morocco':'#C1272D','Ghana':'#006B3F','Ivory Coast':'#FF8000',
  'Cameroon':'#007A5E','Algeria':'#006233','Egypt':'#CC0001','Tunisia':'#E70013',
  'Cape Verde':'#003893','Nigeria':'#008751','Australia':'#FFCD00',
  'Iran':'#239F40','Saudi Arabia':'#006C35','Qatar':'#8D1B3D',
  'Switzerland':'#D52B1E','Poland':'#DC143C','Croatia':'#FF0000',
  'Denmark':'#C60C30','Turkey':'#E30A17','Scotland':'#003399',
  'Austria':'#ED2939','Colombia':'#FCD116','Ecuador':'#FFD100',
  'Peru':'#D91023','Chile':'#D52B1E','Canada':'#FF0000',
  'Panama':'#005293','Costa Rica':'#002B7F','Honduras':'#0073CF',
};
function teamHex(t) { return TEAM_COLORS[t] || '#3a3630'; }
function teamRgb(t) { return hexToRgb(teamHex(t)); }

export function initOverview3D(mount, data, onPick, hooks) {
  if (!overview3DAvailable() || !mount) return null;
  const THREE = window.THREE;

  // ---- Derive bracket data from feeds ----------------------------------------
  const B      = data.bracket || {};
  const Rounds = B.rounds || {};
  const report = data.report || {};
  const odds   = report.title_odds || [];
  const oddsOf = {}, isoOf = {}, flagOf = {}, ccOf = {};
  odds.forEach(o => { oddsOf[o.team] = o.p_win; if (o.iso2) isoOf[o.team] = o.iso2;
    if (o.flag) flagOf[o.team] = o.flag; if (o.confed_color) ccOf[o.team] = o.confed_color; });

  function note(c) { if (!c || !c.team) return;
    if (c.iso2) isoOf[c.team] = c.iso2; if (c.flag) flagOf[c.team] = c.flag;
    if (c.confed_color) ccOf[c.team] = c.confed_color; }

  (B.r32 || []).forEach(t => { note(t.a); note(t.b); });
  Object.values(Rounds).forEach(rd => (rd || []).forEach(t => { note(t && t.a); note(t && t.b); }));
  odds.forEach(note);

  const champCard = (() => {
    const fl = Rounds.final ? Rounds.final : [];
    if (fl.length && fl[0] && fl[0].winner) return { team: fl[0].winner };
    const sf = Rounds.sf || [];
    const sfW = sf.map(t => t && (t.winner === (t.a || {}).team ? t.a : t.b)).filter(Boolean);
    if (sfW.length >= 2) return (oddsOf[sfW[0].team] ?? -1) >= (oddsOf[sfW[1].team] ?? -1) ? sfW[0] : sfW[1];
    return B.champion || (odds[0] && { team: odds[0].team }) || {};
  })();
  const champ = champCard && champCard.team;

  // Retrieve ties for each round
  function getTies(rkey) {
    if (rkey === 'r32') return B.r32 || [];
    return Rounds[rkey] || [];
  }

  // ---- Renderer / scene -------------------------------------------------------
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'display:block;width:100%;height:100%;cursor:grab;outline:none;touch-action:none';
  canvas.setAttribute('tabindex', '0');
  canvas.setAttribute('role', 'application');
  canvas.setAttribute('aria-label',
    '3D knockout bracket. R32 to Final. Drag to orbit, scroll to zoom, tap a panel to open team profile.');
  mount.innerHTML = ''; mount.appendChild(canvas);

  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
  renderer.setClearColor(0x0a0905, 1);
  renderer.shadowMap && (renderer.shadowMap.enabled = true);
  if ('outputEncoding' in renderer && THREE.sRGBEncoding) renderer.outputEncoding = THREE.sRGBEncoding;

  const scene = new THREE.Scene();
  scene.fog = new THREE.FogExp2(0x0a0905, 0.004);

  const camera = new THREE.PerspectiveCamera(50, 2, 0.5, 1000);

  // ---- Lighting ---------------------------------------------------------------
  scene.add(new THREE.AmbientLight(0xc8c4b8, 0.55));

  const dLight = new THREE.DirectionalLight(0xffe4b0, 1.15);
  dLight.position.set(-30, 60, -40); scene.add(dLight);

  const fillLight = new THREE.DirectionalLight(0x8ab4d8, 0.45);
  fillLight.position.set(40, 20, 60); scene.add(fillLight);

  // Key light for champion panel (gold)
  const champLight = new THREE.PointLight(0xffe060, 2.2, 80);
  champLight.position.set(roundX(4), 5, -15); scene.add(champLight);

  // Rim lights per round
  ROUND_DEFS.forEach((rd, i) => {
    const pl = new THREE.PointLight(0xd0c8b0, 0.35, 120);
    pl.position.set(roundX(rd.xi), 28, rd.zd - 20);
    scene.add(pl);
  });

  const maxAniso = (renderer.capabilities && renderer.capabilities.getMaxAnisotropy &&
    renderer.capabilities.getMaxAnisotropy()) || 1;
  const texLoader = new THREE.TextureLoader(); texLoader.setCrossOrigin('anonymous');

  // ---- Material cache ---------------------------------------------------------
  const disposables = [];
  const fbCache = {}, texByTeam = {}, pendingMats = {};

  function isoOfTeam(t) {
    if (isoOf[t]) return isoOf[t];
    const u = flagOf[t] || '';
    const m = u.match(/\/([a-z]{2}(?:-[a-z]+)?)\.svg/i);
    return m ? m[1].toLowerCase() : null;
  }
  function pngUrl(t) { const iso = isoOfTeam(t); return iso ? `https://flagcdn.com/w160/${iso}.png` : null; }

  function fallbackTex(team) {
    if (fbCache[team]) return fbCache[team];
    const c = document.createElement('canvas'); c.width = 128; c.height = 72;
    const g = c.getContext('2d');
    const [r2, g2, b2] = teamRgb(team);
    g.fillStyle = `rgb(${r2*255|0},${g2*255|0},${b2*255|0})`;
    g.fillRect(0, 0, 128, 72);
    g.fillStyle = 'rgba(0,0,0,.3)'; g.fillRect(0, 50, 128, 22);
    g.fillStyle = '#f0e2c2'; g.font = 'bold 22px Arial';
    g.textAlign = 'center'; g.textBaseline = 'middle';
    g.fillText((isoOfTeam(team) || team.slice(0, 3)).toUpperCase(), 64, 61);
    g.strokeStyle = 'rgba(227,165,18,.9)'; g.lineWidth = 5;
    g.strokeRect(2, 2, 124, 68);
    const t = new THREE.CanvasTexture(c);
    if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
    disposables.push(t); fbCache[team] = t; return t;
  }

  function flagMat(team, isChamp) {
    const baseTex = texByTeam[team] || fallbackTex(team);
    const mat = new THREE.MeshStandardMaterial({
      map: baseTex,
      side: THREE.FrontSide,
      roughness: 0.45, metalness: isChamp ? 0.6 : 0.0,
      emissive: isChamp ? new THREE.Color(0xffcc00) : new THREE.Color(0x000000),
      emissiveIntensity: isChamp ? 0.28 : 0.0,
    });
    disposables.push(mat);
    if (!texByTeam[team]) {
      const url = pngUrl(team);
      if (url) {
        if (pendingMats[team]) { pendingMats[team].push(mat); }
        else {
          pendingMats[team] = [mat];
          texLoader.load(url, t => {
            if (!t.image || !t.image.width) { pendingMats[team] = null; return; }
            if (THREE.sRGBEncoding) t.encoding = THREE.sRGBEncoding;
            t.anisotropy = maxAniso; t.minFilter = THREE.LinearMipmapLinearFilter;
            t.needsUpdate = true; disposables.push(t); texByTeam[team] = t;
            (pendingMats[team] || []).forEach(m => { m.map = t; m.needsUpdate = true; });
            pendingMats[team] = null; requestRender();
          }, undefined, () => { pendingMats[team] = null; });
        }
      }
    }
    return mat;
  }

  function solidMat(hexColor, rough = 0.55, metal = 0.0, emissCol = null, emissInt = 0) {
    const m = new THREE.MeshStandardMaterial({
      color: hexColor, roughness: rough, metalness: metal,
      emissive: emissCol ? new THREE.Color(emissCol) : new THREE.Color(0),
      emissiveIntensity: emissInt,
    });
    disposables.push(m); return m;
  }

  // ---- Bracket tree geometry build -------------------------------------------
  const pickTargets = [];      // for raycasting (front-face meshes only)
  const teamByMesh  = new Map();

  function buildBracket() {
    ROUND_DEFS.forEach((rd, ri) => {
      const ties   = getTies(rd.key);
      const xc     = roundX(rd.xi);
      const zd     = rd.zd;
      const yCents = matchYCentres(rd.n, rd.ySpacing);

      // Clamp ties list to expected length
      const tieList = Array.from({ length: rd.n }, (_, i) => ties[i] || null);

      tieList.forEach((tie, mi) => {
        const yc = yCents[mi];
        const teamA = (tie && tie.a && tie.a.team) || '?';
        const teamB = (tie && tie.b && tie.b.team) || '?';
        const winner = tie && tie.winner;
        const played = !!(tie && tie.played);
        const pick   = tie && tie.pick;

        [teamA, teamB].forEach((team, si) => {
          const ySlot = yc + (si === 0 ? (SLOT_GAP / 2 + SLOT_H / 2) : -(SLOT_GAP / 2 + SLOT_H / 2));
          const isChamp = team === champ;
          const isWinner = played && team === winner;
          const isPick   = !played && team === pick;

          // -- Main flag panel (box) --
          const boxGeo = new THREE.BoxGeometry(PAN_W, SLOT_H, PAN_D);
          disposables.push(boxGeo);

          // Create 6 materials (one per face: +x,-x,+y,-y,+z,-z)
          // +z face = flag texture (faces camera); others are solid
          const panelBase = isChamp ? 0xd4a015 : 0x2a271f;
          const panelDark = isChamp ? 0x7a5c08 : 0x1a1812;
          const mats = [
            solidMat(panelDark, 0.8),          // +x right
            solidMat(panelDark, 0.8),          // -x left (will add stripe)
            solidMat(isChamp ? 0xffd040 : 0x3a3528, 0.4, isChamp ? 0.6 : 0), // +y top
            solidMat(panelDark, 0.9),          // -y bottom
            flagMat(team, isChamp),            // +z front (flag)
            solidMat(panelBase, 0.9),          // -z back
          ];
          const mesh = new THREE.Mesh(boxGeo, mats);
          mesh.position.set(xc, ySlot, zd);
          mesh.userData = { team, stage: ri, ri, mi, si };
          scene.add(mesh);
          pickTargets.push(mesh);
          teamByMesh.set(mesh, team);

          // -- Team-colour stripe on left edge --
          const stripeGeo = new THREE.BoxGeometry(STRP_W, SLOT_H + 0.02, PAN_D + 0.04);
          disposables.push(stripeGeo);
          const [cr, cg, cb] = teamRgb(team);
          const stripeMat = solidMat(
            (cr * 255) << 16 | (cg * 255) << 8 | (cb * 255),
            0.65, 0, null, 0
          );
          // Use confed or team colour directly
          const stripeHex = parseInt((teamHex(team) || '#3a3630').replace('#',''), 16);
          const stripeMat2 = solidMat(stripeHex, 0.6);
          const stripe = new THREE.Mesh(stripeGeo, stripeMat2);
          stripe.position.set(xc - PAN_W / 2 + STRP_W / 2, ySlot, zd);
          scene.add(stripe);

          // -- Gold outline for champion or winner --
          if (isChamp || isWinner) {
            const outlineGeo = new THREE.BoxGeometry(PAN_W + 0.32, SLOT_H + 0.32, PAN_D + 0.06);
            disposables.push(outlineGeo);
            const outlineM = solidMat(GOLD, 0.35, 0.85, GOLD, 0.25);
            const outline = new THREE.Mesh(outlineGeo, outlineM);
            outline.position.set(xc, ySlot, zd - 0.1);
            scene.add(outline);
          } else if (isPick) {
            // Subtle gold ring for model pick
            const pickGeo = new THREE.BoxGeometry(PAN_W + 0.18, SLOT_H + 0.18, PAN_D + 0.04);
            disposables.push(pickGeo);
            const pickM = solidMat(GOLDDP, 0.5, 0.4, null, 0);
            const pickMesh = new THREE.Mesh(pickGeo, pickM);
            pickMesh.position.set(xc, ySlot, zd - 0.08);
            scene.add(pickMesh);
          }
        });

        // -- Match divider line (separator between team A / B slots) --
        const divGeo = new THREE.BoxGeometry(PAN_W, 0.06, PAN_D * 0.7);
        disposables.push(divGeo);
        const divMat = solidMat(0xe3a512, 0.5, 0.3);
        const divMesh = new THREE.Mesh(divGeo, divMat);
        divMesh.position.set(xc, yc, zd + PAN_D * 0.15);
        scene.add(divMesh);

        // -- Bracket arm connectors (to next round) --
        if (ri < ROUND_DEFS.length - 1) {
          const nextRd  = ROUND_DEFS[ri + 1];
          const nxc     = roundX(nextRd.xi);
          const nzd     = nextRd.zd;
          const pairI   = Math.floor(mi / 2);
          const nyCents = matchYCentres(nextRd.n, nextRd.ySpacing);
          const nyc     = nyCents[pairI] || 0;
          const connZ   = (zd + nzd) / 2;   // connector sits at midpoint z
          const xGap    = nxc - PAN_W / 2 - (xc + PAN_W / 2);   // gap between columns
          const midX    = xc + PAN_W / 2 + xGap / 2;

          const armMat  = solidMat(0x5a5040, 0.8);

          // Horizontal arm: right edge of match → midpoint x
          const hGeo = new THREE.BoxGeometry(xGap / 2 + 0.05, ARM_H, ARM_D);
          disposables.push(hGeo);
          const hMesh = new THREE.Mesh(hGeo, armMat);
          hMesh.position.set(xc + PAN_W / 2 + (xGap / 2) / 2, yc, connZ);
          scene.add(hMesh);

          // Vertical arm: current match y → pair midpoint y (drawn once per pair, by even index)
          if (mi % 2 === 0 && mi + 1 < rd.n) {
            const ycPair = yCents[mi + 1];
            const vLen   = Math.abs(yc - ycPair);
            const vGeo   = new THREE.BoxGeometry(ARM_H, vLen, ARM_D);
            disposables.push(vGeo);
            const vMesh  = new THREE.Mesh(vGeo, armMat);
            vMesh.position.set(midX, (yc + ycPair) / 2, connZ);
            scene.add(vMesh);
          }

          // Horizontal arm: midpoint x → left edge of next round match
          const hGeo2 = new THREE.BoxGeometry(xGap / 2 + 0.05, ARM_H, ARM_D);
          disposables.push(hGeo2);
          const hMesh2 = new THREE.Mesh(hGeo2, armMat);
          hMesh2.position.set(midX + (xGap / 2) / 2, nyc, connZ);
          scene.add(hMesh2);
        }
      });

      // -- Round label text (canvas billboard) --
      const labelCanvas = document.createElement('canvas');
      labelCanvas.width = 256; labelCanvas.height = 80;
      const lc = labelCanvas.getContext('2d');
      lc.clearRect(0, 0, 256, 80);
      lc.fillStyle = 'rgba(0,0,0,0.55)';
      lc.roundRect ? lc.roundRect(4, 4, 248, 72, 10) : lc.fillRect(4, 4, 248, 72);
      lc.fill();
      lc.fillStyle = '#e3a512'; lc.font = 'bold 28px Arial';
      lc.textAlign = 'center'; lc.textBaseline = 'middle';
      lc.fillText(rd.key.toUpperCase().replace('FINAL','FINAL').replace('R32','ROUND OF 32')
                         .replace('R16','ROUND OF 16').replace('QF','QUARTER-FINALS')
                         .replace('SF','SEMI-FINALS'), 128, 40);
      const lblTex = new THREE.CanvasTexture(labelCanvas);
      if (THREE.sRGBEncoding) lblTex.encoding = THREE.sRGBEncoding;
      disposables.push(lblTex);
      const lblGeo = new THREE.PlaneGeometry(12, 3.2); disposables.push(lblGeo);
      const lblMat = new THREE.MeshBasicMaterial({ map: lblTex, transparent: true, side: THREE.DoubleSide });
      disposables.push(lblMat);
      const lbl = new THREE.Mesh(lblGeo, lblMat);
      const topY = (rd.n / 2) * rd.ySpacing + 4.5;
      lbl.position.set(xc, topY, zd);
      scene.add(lbl);
    });
  }

  buildBracket();

  // ---- Floor / stage platform -------------------------------------------------
  const floorGeo = new THREE.BoxGeometry(STAGE_W * 5 + 10, 0.3, 50);
  disposables.push(floorGeo);
  const floorMat = solidMat(0x1a1810, 0.9);
  const floor = new THREE.Mesh(floorGeo, floorMat);
  floor.position.set(0, -(SLOT_H * 2 + SLOT_GAP) / 2 - 1.8, 0);
  scene.add(floor);

  // ---- Camera orbit state -----------------------------------------------------
  let cs     = 2;   // current focused round index (default: QF, centre)
  let picked = null;
  const target  = new THREE.Vector3(0, 0, 0);
  const targetT = new THREE.Vector3(0, 0, 0);
  let dist   = 95, distT  = 80;
  let yaw    = 0.12, yawT = 0.12;
  let pitch  = 0.18, pitchT = 0.18;
  const YAW_LIM = 1.2, PITCH_MIN = -0.05, PITCH_MAX = 0.85;
  const DIST_MIN = 22, DIST_MAX = 180;
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  function focusRound(i) {
    cs = clamp(i, 0, ROUND_DEFS.length - 1);
    const rd  = ROUND_DEFS[cs];
    const txc = roundX(rd.xi);
    targetT.set(txc, 0, rd.zd);
    // Fit the round's y-extent into view
    const halfH = (rd.n / 2) * rd.ySpacing;
    distT  = clamp(Math.max(halfH * 1.4 + 18, 30), DIST_MIN, DIST_MAX);
    yawT   = 0.10; pitchT = 0.18;
    if (picked && picked.userData.ri !== cs) {
      picked.scale.set(1, 1, 1); picked = null;
    }
    // Opacity: full for focused round, dim others
    scene.traverse(obj => {
      if (obj.isMesh && obj.userData.ri !== undefined) {
        const onStage = obj.userData.ri === cs;
        if (Array.isArray(obj.material)) {
          obj.material.forEach(m => { if (m.opacity !== undefined || m.transparent) {
            m.transparent = true; m.opacity = onStage ? 1 : 0.28; m.needsUpdate = true; }});
        } else if (obj.material) {
          obj.material.transparent = true;
          obj.material.opacity = onStage ? 1 : 0.28;
          obj.material.needsUpdate = true;
        }
      }
    });
    if (ui.title) ui.title.textContent = rd.key.toUpperCase().replace('R32','Round of 32')
      .replace('R16','Round of 16').replace('QF','Quarter-finals')
      .replace('SF','Semi-finals').replace('FINAL','Final')
      + ' · ' + rd.n + ' match' + (rd.n > 1 ? 'es' : '');
    [...ui.rail.children].forEach((b, k) => b.classList.toggle('on', k === cs));
    requestRender();
  }

  // ---- UI chrome --------------------------------------------------------------
  const ui = buildUI(mount);
  ui.rail.innerHTML = '';
  ROUND_DEFS.forEach((rd, i) => {
    const b = document.createElement('button'); b.className = 'o3d-btn';
    b.textContent = rd.key.toUpperCase();
    b.title = rd.key.replace('r32','Round of 32').replace('r16','Round of 16')
              .replace('qf','Quarter-finals').replace('sf','Semi-finals').replace('final','Final');
    b.setAttribute('aria-label', b.title);
    b.onclick = () => focusRound(i); ui.rail.appendChild(b);
  });
  ui.prev.onclick = () => focusRound(cs - 1);
  ui.next.onclick = () => focusRound(cs + 1);

  // ---- Interaction: orbit + pick ----------------------------------------------
  const ray = new THREE.Raycaster(), mouse = new THREE.Vector2();
  const ptrs = new Map(); let moved = 0, lastPinch = 0;
  const avg = () => {
    let x = 0, y = 0; ptrs.forEach(p => { x += p.x; y += p.y; });
    const n = ptrs.size || 1; return { x: x / n, y: y / n };
  };
  const pinchDist = () => {
    const a = [...ptrs.values()]; if (a.length < 2) return 0;
    return Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y);
  };
  const onDown = e => {
    canvas.setPointerCapture && canvas.setPointerCapture(e.pointerId);
    ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
    moved = 0; lastPinch = pinchDist(); canvas.style.cursor = 'grabbing'; requestRender();
  };
  const onMove = e => {
    if (!ptrs.has(e.pointerId)) return;
    const prev = avg(); ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); const now = avg();
    if (ptrs.size >= 2) {
      const pd = pinchDist();
      if (lastPinch) distT = clamp(distT * (lastPinch / (pd || lastPinch)), DIST_MIN, DIST_MAX);
      lastPinch = pd; requestRender(); return;
    }
    const dx = now.x - prev.x, dy = now.y - prev.y; moved += Math.abs(dx) + Math.abs(dy);
    yawT   = clamp(yawT   + dx * 0.005, -YAW_LIM, YAW_LIM);
    pitchT = clamp(pitchT - dy * 0.004, PITCH_MIN, PITCH_MAX); requestRender();
  };
  const onUp = e => {
    const wasTap = ptrs.size === 1 && moved < 7;
    ptrs.delete(e.pointerId); lastPinch = pinchDist();
    if (!ptrs.size) canvas.style.cursor = 'grab';
    if (wasTap) {
      const r = canvas.getBoundingClientRect();
      mouse.x = ((e.clientX - r.left) / r.width)  * 2 - 1;
      mouse.y = -((e.clientY - r.top)  / r.height) * 2 + 1;
      ray.setFromCamera(mouse, camera);
      const hits = ray.intersectObjects(pickTargets, false);
      if (hits.length) {
        if (picked) picked.scale.set(1, 1, 1);
        picked = hits[0].object; picked.scale.set(1.04, 1.04, 1.04);
        if (onPick) onPick(teamByMesh.get(picked) || picked.userData.team, canvas);
        requestRender();
      }
    }
  };
  const onWheel = e => {
    e.preventDefault(); distT = clamp(distT + e.deltaY * 0.06, DIST_MIN, DIST_MAX); requestRender();
  };
  const onKeyDown = e => {
    const k = e.key.toLowerCase();
    if (k === 'arrowright' || k === 'd') { e.preventDefault(); focusRound(cs + 1); return; }
    if (k === 'arrowleft'  || k === 'a') { e.preventDefault(); focusRound(cs - 1); return; }
    if (k === '+' || k === '=') { distT = clamp(distT - 8, DIST_MIN, DIST_MAX); requestRender(); }
    if (k === '-' || k === '_') { distT = clamp(distT + 8, DIST_MIN, DIST_MAX); requestRender(); }
  };
  const onResize = () => {
    const w = mount.clientWidth || 800, h = mount.clientHeight || 500;
    renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
    renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix();
    requestRender();
  };

  canvas.addEventListener('pointerdown', onDown);
  canvas.addEventListener('pointermove', onMove);
  canvas.addEventListener('pointerup',   onUp);
  canvas.addEventListener('pointercancel', onUp);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('keydown', onKeyDown);
  window.addEventListener('resize', onResize);

  // ---- Render-on-demand loop --------------------------------------------------
  let raf = 0, alive = true, firstFrame = true, rendering = false, onScreen = true, tabOn = true;
  const visible = () => onScreen && tabOn;
  function settled() {
    return ptrs.size === 0
      && Math.abs(dist  - distT)  < 0.08
      && Math.abs(yaw   - yawT)   < 0.002
      && Math.abs(pitch - pitchT) < 0.002
      && target.distanceToSquared(targetT) < 0.02;
  }
  // Gentle champion light pulse
  let champT = 0;
  function frame() {
    if (!alive) { rendering = false; return; }
    target.lerp(targetT, 0.1);
    dist  += (distT  - dist)  * 0.10;
    yaw   += (yawT   - yaw)   * 0.12;
    pitch += (pitchT - pitch) * 0.12;

    // Champion light pulse
    champT += 0.018;
    champLight.intensity = 1.9 + 0.6 * Math.sin(champT);

    // Orbit camera
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    camera.position.set(
      target.x + dist * Math.sin(yaw) * cp,
      target.y + dist * sp,
      target.z + dist * Math.cos(yaw) * cp
    );
    camera.lookAt(target);

    try { renderer.render(scene, camera); }
    catch (err) { alive = false; rendering = false; if (hooks && hooks.onError) hooks.onError(err); return; }
    if (firstFrame) { firstFrame = false; if (hooks && hooks.onReady) hooks.onReady(); }
    if (visible() && !settled()) { raf = requestAnimationFrame(frame); } else { rendering = false; }
  }
  function requestRender() { if (alive && visible() && !rendering) { rendering = true; raf = requestAnimationFrame(frame); } }

  let io = null;
  try {
    io = new IntersectionObserver(es => { onScreen = !!es[0] && es[0].isIntersecting; if (onScreen) requestRender(); }, { threshold: 0.01 });
    io.observe(mount);
  } catch (e) {}
  const onVis = () => { tabOn = !document.hidden; if (tabOn) requestRender(); };
  document.addEventListener('visibilitychange', onVis);

  onResize(); focusRound(cs); requestRender();

  return {
    destroy() {
      alive = false; cancelAnimationFrame(raf);
      canvas.removeEventListener('pointerdown', onDown);
      canvas.removeEventListener('pointermove', onMove);
      canvas.removeEventListener('pointerup',   onUp);
      canvas.removeEventListener('pointercancel', onUp);
      canvas.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('resize',  onResize);
      document.removeEventListener('visibilitychange', onVis);
      if (io) { try { io.disconnect(); } catch (e) {} }
      disposables.forEach(d => { try { d.dispose && d.dispose(); } catch (e) {} });
      try { renderer.dispose(); } catch (e) {}
      mount.innerHTML = '';
    }
  };
}

// ---- UI builder -------------------------------------------------------------
function buildUI(mount) {
  if (getComputedStyle(mount).position === 'static') mount.style.position = 'relative';
  const base = 'position:absolute;font-family:inherit;z-index:2;';
  const title = el('div', base + 'left:14px;top:12px;font-size:15px;color:#f0e2c2;' +
    'text-shadow:0 1px 4px rgba(0,0,0,.7);letter-spacing:.05em;');
  const hint  = el('div', base + 'left:14px;bottom:54px;font-size:11px;color:#b8a880;opacity:.85;' +
    'text-shadow:0 1px 3px rgba(0,0,0,.8);');
  hint.textContent = 'drag to orbit · scroll / pinch to zoom · tap a panel';

  const bar  = el('div', base + 'left:0;right:0;bottom:12px;display:flex;justify-content:center;' +
    'gap:5px;flex-wrap:wrap;padding:0 10px;');
  const prev = btn('‹'), rail = el('div', 'display:flex;gap:4px;flex-wrap:wrap;justify-content:center;'), next = btn('›');
  prev.setAttribute('aria-label', 'Previous round'); next.setAttribute('aria-label', 'Next round');
  bar.append(prev, rail, next);

  const style = document.createElement('style');
  style.textContent = [
    '.o3d-btn{cursor:pointer;border:1px solid #3a3630;border-radius:7px;padding:6px 10px;',
    'font-size:11px;background:rgba(20,16,10,.82);color:#cdbf9f;font-family:inherit;',
    'min-width:32px;transition:border-color .15s,background .15s}',
    '.o3d-btn:hover{border-color:#e3a512;color:#f0e2c2}',
    '.o3d-btn.on{background:#e3a512;color:#1c1407;border-color:#e3a512}',
  ].join('');

  mount.append(style, title, hint, bar);
  return { title, rail, prev, next };

  function el(tag, s) { const e = document.createElement(tag); e.style.cssText = s; return e; }
  function btn(t)  { const b = document.createElement('button'); b.className = 'o3d-btn'; b.textContent = t; return b; }
}
