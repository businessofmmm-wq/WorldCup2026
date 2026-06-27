/*
 * collapse.js — UI controller for "Collapse: One Nation, Every Timeline" (Page 09).
 *
 * Owns the #collapseApp mount. Drives the deterministic runGen() generator from
 * collapse-core.js: yields a 'decide' step per player match (we render the quantum
 * board + live odds), a 'collapse' step (we animate the wavefunction collapsing to
 * the sampled scoreline), and returns an 'end' summary (we show how far the timeline
 * survived + a shareable card). Daily Challenge plays today's frozen shared seed;
 * Free Play re-rolls the field each run. Personal run history + handle live in
 * localStorage; the daily leaderboard is wired in functions/api (Phase 5).
 */
import { runGen, previewMatch, OPERATORS, ROUND_LABEL } from './collapse-core.js';

// --------------------------------------------------------------------------- //
const $ = (s, r = document) => r.querySelector(s);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const pct = x => (100 * x).toFixed(x >= 0.1 ? 0 : 1) + '%';
const FLAG = iso => iso ? `https://flagcdn.com/${iso}.svg` : null;
const REDUCED = matchMedia('(prefers-reduced-motion: reduce)').matches;
const LS_RUNS = 'wcpa_collapse_runs', LS_HANDLE = 'wcpa_collapse_handle';
// Set after creating the Turnstile widget (see LEADERBOARD-SETUP.md). Empty = no
// widget; submit still works once the daily board is live with no secret set.
const TURNSTILE_SITEKEY = '';

const S = {
  mode: 'daily', team: null, handle: localStorage.getItem(LS_HANDLE) || '',
  daily: null, free: null, data: null, seed: null, gen: null, ctx: null, choice: [],
  lastSummary: null, root: null, tab: 'runs', turnstileToken: '',
};

function flagImg(team, meta, cls) {
  const iso = (meta || {}).iso2;
  const url = FLAG(iso);
  return url
    ? `<img class="${cls}" src="${url}" alt="" loading="lazy" />`
    : `<span class="${cls} noflag">${esc((team || '?').slice(0, 3).toUpperCase())}</span>`;
}

// --------------------------------------------------------------------------- //
// Boot
// --------------------------------------------------------------------------- //
async function boot() {
  const root = document.getElementById('collapseApp');
  if (!root) return;
  S.root = root;
  const [daily, free] = await Promise.all([
    fetch('/api/daily.json').then(r => r.json()).catch(() => null),
    fetch('/api/collapse.json').then(r => r.json()).catch(() => null),
  ]);
  S.daily = daily; S.free = free;
  if (!free || !(daily && daily.snapshot)) {
    root.innerHTML = '<p class="loading">the multiverse is offline — try a reload.</p>';
    return;
  }
  renderShell();
  renderSetup();
}

function renderShell() {
  S.root.innerHTML = '';
  const wrap = el('div', 'cl-wrap');
  wrap.appendChild(el('div', 'cl-stage', '<p class="loading">…</p>'));
  const rail = el('aside', 'cl-rail');
  rail.innerHTML = `
    <div class="cl-tabs" role="tablist">
      <button class="cl-tab active" data-tab="runs">Your Runs</button>
      <button class="cl-tab" data-tab="board">Daily Board</button>
    </div>
    <div class="cl-railbody"></div>`;
  wrap.appendChild(rail);
  S.root.appendChild(wrap);
  rail.querySelectorAll('.cl-tab').forEach(b => b.addEventListener('click', () => {
    S.tab = b.dataset.tab;
    rail.querySelectorAll('.cl-tab').forEach(x => x.classList.toggle('active', x === b));
    renderRail();
  }));
  renderRail();
}

const stage = () => $('.cl-stage', S.root);

// --------------------------------------------------------------------------- //
// Setup screen — mode, nation, handle
// --------------------------------------------------------------------------- //
function renderSetup() {
  const teams = Object.keys(S.free.teams).sort((a, b) => S.free.teams[b].elo - S.free.teams[a].elo);
  const st = stage();
  st.innerHTML = '';
  const card = el('div', 'cl-setup');

  const modeRow = el('div', 'cl-modes');
  modeRow.innerHTML = `
    <button class="cl-mode ${S.mode === 'daily' ? 'on' : ''}" data-mode="daily">
      <span class="cl-mode-k">Daily Challenge</span>
      <span class="cl-mode-d">One shared, frozen timeline — ${esc(S.daily.date)}. Ranked on the global board.</span>
    </button>
    <button class="cl-mode ${S.mode === 'free' ? 'on' : ''}" data-mode="free">
      <span class="cl-mode-k">Free Play</span>
      <span class="cl-mode-d">A fresh random timeline every run. Saved to your runs, not the board.</span>
    </button>`;
  card.appendChild(modeRow);

  card.appendChild(el('h3', 'cl-h', 'Choose your nation'));
  card.appendChild(el('p', 'cl-sub', 'Weaker sides score more on the board — a deep run with a minnow is the real flex.'));
  const grid = el('div', 'cl-teamgrid');
  const maxElo = S.free.teams[teams[0]].elo, minElo = S.free.teams[teams[teams.length - 1]].elo;
  for (const t of teams) {
    const m = S.free.teams[t];
    const tier = Math.round(1 + 4 * (m.elo - minElo) / (maxElo - minElo)); // 1..5 stars
    const b = el('button', 'cl-team' + (S.team === t ? ' on' : ''));
    b.dataset.team = t;
    b.innerHTML = `${flagImg(t, m, 'cl-team-flag')}
      <span class="cl-team-name">${esc(t)}</span>
      <span class="cl-team-tier" title="model strength">${'★'.repeat(tier)}${'·'.repeat(5 - tier)}</span>`;
    grid.appendChild(b);
  }
  card.appendChild(grid);

  const foot = el('div', 'cl-setup-foot');
  foot.innerHTML = `
    <label class="cl-handle">Your tag
      <input id="clHandle" maxlength="18" placeholder="e.g. quantumkeeper" value="${esc(S.handle)}" />
    </label>
    <button class="cl-begin" id="clBegin" disabled>Pick a nation</button>`;
  card.appendChild(foot);
  st.appendChild(card);

  modeRow.querySelectorAll('.cl-mode').forEach(btn => btn.addEventListener('click', () => {
    S.mode = btn.dataset.mode; renderSetup();
  }));
  grid.querySelectorAll('.cl-team').forEach(btn => btn.addEventListener('click', () => {
    S.team = btn.dataset.team;
    grid.querySelectorAll('.cl-team').forEach(x => x.classList.toggle('on', x === btn));
    const beginBtn = $('#clBegin'); beginBtn.disabled = false;
    beginBtn.textContent = `Run with ${S.team} →`;
  }));
  $('#clHandle').addEventListener('input', e => {
    S.handle = e.target.value.trim(); localStorage.setItem(LS_HANDLE, S.handle);
  });
  $('#clBegin').addEventListener('click', beginRun);
}

// --------------------------------------------------------------------------- //
// Run driver
// --------------------------------------------------------------------------- //
function beginRun() {
  if (!S.team) return;
  S.data = S.mode === 'daily' ? S.daily.snapshot : S.free;
  S.seed = S.mode === 'daily' ? S.daily.seed : (Math.random() * 2 ** 32) >>> 0;
  S.gen = runGen(S.seed, S.team, S.data);
  const r = S.gen.next();
  if (r.done) return renderEnd(r.value);
  onDecide(r.value);
}

function onDecide(step) {
  S.ctx = step.ctx; S.choice = [];
  renderMatch(step);
}

function commit() {
  const r = S.gen.next(S.choice);          // -> 'collapse'
  renderCollapse(r.value, () => {
    const nxt = S.gen.next();              // -> next 'decide' | end
    if (nxt.done) renderEnd(nxt.value);
    else {
      if (S.ctx.phase === 'group' && nxt.value.ctx && nxt.value.ctx.phase === 'ko') toast('Through to the knockouts! ⚽');
      onDecide(nxt.value);
    }
  });
}

// --------------------------------------------------------------------------- //
// Match board
// --------------------------------------------------------------------------- //
function playerView(odds, isHome) {
  return isHome ? { win: odds.pHome, draw: odds.pDraw, loss: odds.pAway }
    : { win: odds.pAway, draw: odds.pDraw, loss: odds.pHome };
}

function renderMatch(step) {
  const c = step.ctx, isHome = c.playerIsHome;
  const st = stage(); st.innerHTML = '';
  const board = el('div', 'cl-match');

  const decoPct = Math.round(step.decoherence * 100);
  board.innerHTML = `
    <div class="cl-match-head">
      <span class="cl-round">${esc(ROUND_LABEL[c.roundName])}</span>
      ${decoPct ? `<span class="cl-deco" title="decoherence — rising noise deep in the run">decoherence +${decoPct}%</span>` : ''}
    </div>
    <div class="cl-vs">
      <div class="cl-vs-side you">${flagImg(c.playerTeam, S.data.teams[c.playerTeam], 'cl-vs-flag')}<span>${esc(c.playerTeam)}</span><small>you</small></div>
      <span class="cl-vs-x">×</span>
      <div class="cl-vs-side">${flagImg(c.opp, c.oppMeta, 'cl-vs-flag')}<span>${esc(c.opp)}</span><small>Elo ${Math.round(c.oppMeta.elo)}</small></div>
    </div>
    <div class="cl-budget" id="clBudget"></div>
    <div class="cl-ops" id="clOps"></div>
    <div class="cl-readout">
      <div class="cl-odds" id="clOdds"></div>
      <div class="cl-superwrap"><canvas class="cl-super" id="clSuper" width="280" height="280"></canvas>
        <div class="cl-super-axis"><span>your goals ↓ · their goals →</span></div></div>
    </div>
    <button class="cl-collapse" id="clCollapse">⟢ Collapse the wavefunction</button>`;
  st.appendChild(board);

  // operator chips
  const ops = $('#clOps');
  for (const op of OPERATORS) {
    const chip = el('button', 'cl-op');
    chip.dataset.id = op.id;
    chip.innerHTML = `<span class="cl-op-glyph">${op.glyph}</span>
      <span class="cl-op-name">${esc(op.name)}</span>
      <span class="cl-op-cost">${op.cost}q</span>
      <span class="cl-op-desc">${esc(op.desc)}</span>
      <span class="cl-op-q">${esc(op.quantum)}</span>`;
    chip.addEventListener('click', () => toggleOp(op.id));
    ops.appendChild(chip);
  }
  $('#clCollapse').addEventListener('click', commit);
  updateBoard();
}

function spent() { return S.choice.reduce((s, id) => s + OPERATORS.find(o => o.id === id).cost, 0); }

function toggleOp(id) {
  const op = OPERATORS.find(o => o.id === id);
  if (S.choice.includes(id)) S.choice = S.choice.filter(x => x !== id);
  else if (spent() + op.cost <= S.ctx.budget) S.choice.push(id);
  else return; // over budget
  updateBoard();
}

function updateBoard() {
  const c = S.ctx, budget = c.budget, used = spent();
  // budget pips
  const pips = [];
  for (let i = 0; i < budget; i++) pips.push(`<span class="cl-pip ${i < used ? 'on' : ''}"></span>`);
  $('#clBudget').innerHTML = `<span class="cl-budget-lbl">Quanta</span>${pips.join('')}<span class="cl-budget-n">${budget - used} left</span>`;

  // chips state
  S.root.querySelectorAll('.cl-op').forEach(chip => {
    const op = OPERATORS.find(o => o.id === chip.dataset.id);
    const on = S.choice.includes(op.id);
    const afford = on || used + op.cost <= budget;
    chip.classList.toggle('on', on);
    chip.classList.toggle('disabled', !afford);
  });

  // odds — base (no ops) vs current selection, from the player's perspective
  const base = playerView(previewMatch(c, [], S.data).odds, c.playerIsHome);
  const mod = previewMatch(c, S.choice, S.data);
  const pv = playerView(mod.odds, c.playerIsHome);
  $('#clOdds').innerHTML = bar('Win', pv.win, base.win, 'win') + bar('Draw', pv.draw, base.draw, 'draw') + bar('Loss', pv.loss, base.loss, 'loss');

  // superposition heatmap (player oriented)
  drawField($('#clSuper'), mod.grid, c.playerIsHome);
}

function bar(label, v, base, kind) {
  const d = v - base, sign = d > 0.0005 ? '+' : d < -0.0005 ? '' : '';
  const delta = Math.abs(d) < 0.0005 ? '' : `<span class="cl-delta ${d > 0 ? 'up' : 'dn'}">${sign}${(d * 100).toFixed(0)}</span>`;
  return `<div class="cl-bar ${kind}">
      <span class="cl-bar-lbl">${label}</span>
      <span class="cl-bar-track"><span class="cl-bar-fill" style="width:${Math.max(2, v * 100)}%"></span></span>
      <span class="cl-bar-val">${pct(v)} ${delta}</span></div>`;
}

// --------------------------------------------------------------------------- //
// Canvas superposition + collapse animation
// --------------------------------------------------------------------------- //
const NCELL = 7; // show 0..6 goals each axis (captures ~99% of mass)

function playerMatrix(grid, isHome) {
  const M = [];
  for (let p = 0; p < NCELL; p++) { const row = []; for (let o = 0; o < NCELL; o++) row.push(isHome ? grid[p][o] : grid[o][p]); M.push(row); }
  return M;
}

function cssVar(name) { try { return getComputedStyle(document.documentElement).getPropertyValue(name).trim(); } catch { return ''; } }

function drawField(canvas, grid, isHome, opts = {}) {
  const ctx = canvas.getContext('2d');
  const W = canvas.width, H = canvas.height, pad = 22, cw = (W - pad) / NCELL, ch = (H - pad) / NCELL;
  const M = playerMatrix(grid, isHome);
  let mx = 0; for (const r of M) for (const v of r) mx = Math.max(mx, v);
  const accent = cssVar('--accent') || '#009C3B', red = cssVar('--accent-2') || '#C1272D';
  ctx.clearRect(0, 0, W, H);
  for (let p = 0; p < NCELL; p++) for (let o = 0; o < NCELL; o++) {
    const v = M[p][o], x = pad + o * cw, y = pad + p * ch;
    let a = Math.sqrt(v / (mx || 1));
    let col = p > o ? accent : p < o ? red : '#9a8f76';
    if (opts.collapseTo) {
      const [tp, to] = opts.collapseTo;
      const isTarget = (p === Math.min(tp, NCELL - 1) && o === Math.min(to, NCELL - 1));
      a = isTarget ? 1 : a * (1 - opts.t);
      if (isTarget) { col = opts.win ? accent : opts.draw ? '#cdbb88' : red; }
    }
    ctx.globalAlpha = 0.10 + 0.9 * a;
    ctx.fillStyle = col;
    roundRect(ctx, x + 1, y + 1, cw - 2, ch - 2, 3); ctx.fill();
  }
  ctx.globalAlpha = 1;
  // axis ticks
  ctx.fillStyle = cssVar('--ink-soft') || '#a99c83';
  ctx.font = '10px "Space Grotesk", sans-serif';
  for (let i = 0; i < NCELL; i++) {
    ctx.fillText(i, pad + i * cw + cw / 2 - 3, 13);
    ctx.fillText(i, 6, pad + i * ch + ch / 2 + 3);
  }
}

function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath(); ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath();
}

function renderCollapse(step, done) {
  const c = step.ctx, isHome = c.playerIsHome;
  const myG = isHome ? step.score[0] : step.score[1], oppG = isHome ? step.score[1] : step.score[0];
  const won = step.advanced === true || (step.outcome === 'win');
  const draw = step.outcome === 'draw';
  const canvas = $('#clSuper');
  const tp = isHome ? step.score[0] : step.score[1], to = isHome ? step.score[1] : step.score[0];
  $('#clCollapse').disabled = true;
  S.root.querySelectorAll('.cl-op').forEach(ch => ch.classList.add('disabled'));

  const finish = () => {
    drawField(canvas, step.grid, isHome, { collapseTo: [tp, to], t: 1, win: won, draw });
    const verdict = step.viaShootout ? (won ? 'WIN on penalties' : 'OUT on penalties')
      : won ? 'ADVANCE' : draw ? 'DRAW' : 'ELIMINATED';
    const banner = el('div', 'cl-collapse-result ' + (won ? 'win' : draw ? 'draw' : 'loss'));
    banner.innerHTML = `<span class="cl-cr-score">${myG}<small>–</small>${oppG}</span><span class="cl-cr-verdict">${verdict}</span>`;
    $('.cl-superwrap').appendChild(banner);
    const btn = el('button', 'cl-collapse next', won ? 'Next match →' : 'See your timeline →');
    btn.addEventListener('click', () => { btn.disabled = true; done(); });
    $('#clCollapse').replaceWith(btn);
  };

  if (REDUCED) { finish(); return; }
  const t0 = performance.now(), DUR = 850;
  (function frame(now) {
    const t = Math.min(1, (now - t0) / DUR);
    drawField(canvas, step.grid, isHome, { collapseTo: [tp, to], t, win: won, draw });
    if (t < 1) requestAnimationFrame(frame); else finish();
  })(performance.now());
}

// --------------------------------------------------------------------------- //
// Run end
// --------------------------------------------------------------------------- //
function renderEnd(sum) {
  S.lastSummary = sum;
  S.lastRunTs = saveRun(sum);
  const st = stage(); st.innerHTML = '';
  const champ = sum.champion;
  const card = el('div', 'cl-end' + (champ ? ' champ' : ''));
  const legs = (sum.path || []).map(leg => {
    const oppMeta = S.data.teams[leg.opp];
    const res = leg.outcome === 'win' ? 'W' : leg.outcome === 'draw' ? 'D' : 'L';
    const my = leg.playerIsHome ? leg.score[0] : leg.score[1], op = leg.playerIsHome ? leg.score[1] : leg.score[0];
    const opNames = (leg.ops || []).map(id => OPERATORS.find(o => o.id === id)?.glyph || '').join(' ');
    return `<div class="cl-leg ${leg.outcome}">
      <span class="cl-leg-rd">${esc(ROUND_LABEL[leg.stage])}</span>
      ${flagImg(leg.opp, oppMeta, 'cl-leg-flag')}
      <span class="cl-leg-opp">${esc(leg.opp)}</span>
      <span class="cl-leg-score">${my}–${op} <b class="r-${res}">${res}</b></span>
      <span class="cl-leg-ops">${opNames}</span></div>`;
  }).join('');

  card.innerHTML = `
    <div class="cl-end-badge">
      ${flagImg(S.team, S.data.teams[S.team], 'cl-end-flag')}
      <div><span class="cl-end-k">${esc(S.team)} — your timeline collapsed at</span>
      <span class="cl-end-round">${champ ? '🏆 CHAMPIONS' : esc(sum.roundLabel)}</span>
      <span class="cl-end-meta">goal margin ${sum.margin >= 0 ? '+' : ''}${sum.margin} · ${S.mode === 'daily' ? 'Daily ' + esc(S.daily.date) : 'Free play'}</span></div>
    </div>
    <div class="cl-path">${legs || '<p class="muted">No matches played.</p>'}</div>
    <div class="cl-end-actions">
      ${S.mode === 'daily' ? '<div class="cl-turnstile" id="clTurnstile"></div><button class="cl-begin" id="clSubmit">Submit to the daily board</button>' : ''}
      <button class="cl-ghost" id="clShare">Download run card</button>
      <button class="cl-ghost" id="clAgain">New run</button>
    </div>`;
  st.appendChild(card);
  $('#clAgain').addEventListener('click', renderSetup);
  $('#clShare').addEventListener('click', () => downloadCard(sum));
  if (S.mode === 'daily') { $('#clSubmit').addEventListener('click', submitRun); mountTurnstile(); }
  renderRail();
}

// Turnstile (optional bot defense) — injected only when a sitekey is configured;
// the board still accepts submissions without it until you set one up.
function mountTurnstile() {
  if (!TURNSTILE_SITEKEY) return;
  if (!window.turnstile && !document.getElementById('cf-ts')) {
    const s = el('script'); s.id = 'cf-ts'; s.async = true; s.defer = true;
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
    document.head.appendChild(s);
  }
  const host = $('#clTurnstile'); if (!host) return;
  (function render() {
    if (window.turnstile && !host.dataset.rendered) {
      host.dataset.rendered = '1';
      window.turnstile.render(host, { sitekey: TURNSTILE_SITEKEY, callback: t => { S.turnstileToken = t; } });
    } else if (!host.dataset.rendered) setTimeout(render, 300);
  })();
}

// --------------------------------------------------------------------------- //
// Local history + rail
// --------------------------------------------------------------------------- //
function loadRuns() { try { return JSON.parse(localStorage.getItem(LS_RUNS)) || []; } catch { return []; } }
function saveRun(sum) {
  const runs = loadRuns();
  const rec = {
    ts: Date.now(), mode: S.mode, date: S.mode === 'daily' ? S.daily.date : null,
    team: S.team, iso: (S.data.teams[S.team] || {}).iso2, seed: S.seed,
    round: sum.roundReached, roundLabel: sum.roundLabel, score: sum.roundScore,
    margin: sum.margin, champion: !!sum.champion,
    ops: (sum.path || []).map(l => l.ops || []),
  };
  runs.unshift(rec);
  localStorage.setItem(LS_RUNS, JSON.stringify(runs.slice(0, 60)));
  return rec.ts;
}
function markSubmitted(ts) {
  const runs = loadRuns();
  const r = runs.find(x => x.ts === ts);
  if (r) { r.sub = 1; localStorage.setItem(LS_RUNS, JSON.stringify(runs)); }
}

function renderRail() {
  const body = $('.cl-railbody', S.root); if (!body) return;
  if (S.tab === 'runs') {
    const runs = loadRuns();
    body.innerHTML = runs.length ? '' : '<p class="cl-empty">No runs yet. Collapse a timeline and it lands here.</p>';
    for (const r of runs.slice(0, 30)) {
      const row = el('div', 'cl-run' + (r.champion ? ' champ' : ''));
      // today's daily runs that never reached the board can be submitted from here
      const canSub = r.mode === 'daily' && r.date === S.daily?.date && !r.sub && Array.isArray(r.ops);
      row.innerHTML = `${flagImg(r.team, { iso2: r.iso }, 'cl-run-flag')}
        <span class="cl-run-team">${esc(r.team)}</span>
        <span class="cl-run-round">${r.champion ? '🏆' : esc(r.roundLabel)}</span>
        <span class="cl-run-tag" title="${r.mode === 'daily' ? 'Daily challenge' : 'Free play'}">${r.mode === 'daily' ? (r.sub ? 'D ✓' : 'D') : 'F'}</span>`;
      if (canSub) {
        const b = el('button', 'cl-run-sub', '↑ board');
        b.title = 'Submit this run to the daily board';
        b.addEventListener('click', () => submitSaved(r, b));
        row.appendChild(b);
      }
      body.appendChild(row);
    }
  } else {
    body.innerHTML = '<p class="cl-empty">loading the daily board…</p>';
    const day = S.daily?.date;
    fetch(`/api/leaderboard?day=${encodeURIComponent(day)}`).then(r => r.ok ? r.json() : Promise.reject())
      .then(d => renderBoard(body, d))
      .catch(() => { body.innerHTML = '<p class="cl-empty">The daily board goes live with the next deploy. Your run is saved locally and will submit then.</p>'; });
  }
}

function renderBoard(body, d) {
  const rows = (d.rows || d.leaderboard || []);
  if (!rows.length) { body.innerHTML = '<p class="cl-empty">No entries yet today — be the first.</p>'; return; }
  body.innerHTML = '';
  rows.slice(0, 50).forEach((r, i) => {
    const row = el('div', 'cl-run');
    row.innerHTML = `<span class="cl-run-rank">${i + 1}</span>
      <span class="cl-run-team">${esc(r.handle || '—')}</span>
      <span class="cl-run-round">${esc(r.team || '')} · ${esc(r.champion ? '🏆 Champion' : (ROUND_LABEL[r.round_reached] || ''))}</span>`;
    body.appendChild(row);
  });
}

// --------------------------------------------------------------------------- //
// Leaderboard submit (Function wired in Phase 5) + share card
// --------------------------------------------------------------------------- //
// POST one run to the verifier. Shared by the end-screen button and the
// "↑ board" buttons on today's saved daily runs in the rail.
async function postRun(payload) {
  const res = await fetch('/api/run/submit', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const out = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(out.error || res.statusText || 'submit failed');
  return out;
}

function showBoardTab() {
  S.tab = 'board';
  S.root.querySelectorAll('.cl-tab').forEach(x => x.classList.toggle('active', x.dataset.tab === 'board'));
  renderRail();
}

async function submitRun() {
  const sum = S.lastSummary; if (!sum) return;
  if (!S.handle) { toast('add a tag on the setup screen first'); return; }
  const btn = $('#clSubmit'); if (btn) { btn.disabled = true; btn.textContent = 'submitting…'; }
  try {
    const out = await postRun({
      day: S.daily.date, handle: S.handle, team: S.team, seed: S.seed,
      ops: (sum.path || []).map(l => l.ops || []),
      claimedRound: sum.roundReached, claimedMargin: sum.margin,
      turnstileToken: S.turnstileToken,
    });
    if (out.note) { toast('verified — board opens with the next deploy'); }
    else {
      markSubmitted(S.lastRunTs);
      toast(out.rank ? `On the board — rank #${out.rank} of ${out.total || out.rank} today ⚽` : 'Submitted to the daily board ⚽');
    }
    if (btn) btn.textContent = 'Submitted ✓';
    showBoardTab();
  } catch (e) {
    toast(`not on the board — ${e.message || 'network hiccup, try again'}`);
    if (btn) { btn.disabled = false; btn.textContent = 'Submit to the daily board'; }
  }
}

async function submitSaved(r, btn) {
  if (!S.handle) { toast('add a tag on the setup screen first'); return; }
  btn.disabled = true; btn.textContent = '…';
  try {
    const out = await postRun({
      day: r.date, handle: S.handle, team: r.team, seed: r.seed,
      ops: r.ops, claimedRound: r.round, claimedMargin: r.margin,
      turnstileToken: S.turnstileToken,
    });
    if (!out.note) markSubmitted(r.ts);
    toast(out.rank ? `On the board — rank #${out.rank} of ${out.total || out.rank} today ⚽` : 'Run verified ⚽');
    showBoardTab();
  } catch (e) {
    toast(`not on the board — ${e.message || 'network hiccup, try again'}`);
    btn.disabled = false; btn.textContent = '↑ board';
  }
}

function downloadCard(sum) {
  const W = 1080, H = 1350, cv = el('canvas'); cv.width = W; cv.height = H;
  const x = cv.getContext('2d');
  const bg = cssVar('--bg') || '#141310', ink = cssVar('--ink') || '#ece3d0', accent = cssVar('--accent') || '#009C3B';
  x.fillStyle = bg; x.fillRect(0, 0, W, H);
  x.fillStyle = accent; x.fillRect(0, 0, W, 16);
  x.fillStyle = ink; x.textAlign = 'center';
  x.font = '700 44px "Space Grotesk", sans-serif'; x.fillText('COLLAPSE — WCPA ’26', W / 2, 150);
  x.font = '900 130px Anton, Impact, sans-serif';
  x.fillText(sum.champion ? 'CHAMPIONS' : (sum.roundLabel || '').toUpperCase(), W / 2, 330);
  x.fillStyle = accent; x.font = '900 90px Anton, Impact, sans-serif';
  x.fillText(S.team.toUpperCase(), W / 2, 450);
  x.fillStyle = ink; x.font = '400 40px "Space Grotesk", sans-serif';
  x.fillText(`${S.mode === 'daily' ? 'Daily ' + S.daily.date : 'Free play'} · goal margin ${sum.margin >= 0 ? '+' : ''}${sum.margin}`, W / 2, 530);
  let y = 660; x.textAlign = 'left'; x.font = '500 38px "Space Grotesk", sans-serif';
  for (const leg of (sum.path || [])) {
    const my = leg.playerIsHome ? leg.score[0] : leg.score[1], op = leg.playerIsHome ? leg.score[1] : leg.score[0];
    const res = leg.outcome === 'win' ? 'W' : leg.outcome === 'draw' ? 'D' : 'L';
    x.fillStyle = leg.outcome === 'win' ? accent : leg.outcome === 'loss' ? (cssVar('--accent-2') || '#C1272D') : ink;
    x.fillText(`${ROUND_LABEL[leg.stage]}  v ${leg.opp}   ${my}–${op}  ${res}`, 120, y);
    y += 62;
  }
  x.fillStyle = ink; x.textAlign = 'center'; x.font = '700 40px "Space Grotesk", sans-serif';
  x.fillText('wcpa26.com', W / 2, H - 70);
  const a = el('a'); a.download = `collapse-${S.team}-${sum.roundReached}.png`; a.href = cv.toDataURL('image/png'); a.click();
}

// --------------------------------------------------------------------------- //
function toast(msg) {
  const t = document.getElementById('toast'); if (!t) return;
  t.textContent = msg; t.hidden = false; clearTimeout(toast._t);
  toast._t = setTimeout(() => { t.hidden = true; }, 2600);
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
