/* =====================================================================
   WORLD CUP '26 — PREDICTION ALBUM  ·  front-end
   Vanilla JS. Fetches the engine's JSON API and renders everything as
   retro stickers + hand-rolled SVG (no chart library — keeps it tiny).
   ===================================================================== */
'use strict';

const API = p => fetch(p).then(r => r.json());
const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

// ----- formatting helpers -------------------------------------------------
const pct = (x, d = 1) => {
  if (x == null) return '—';
  const v = x * 100;
  if (v > 0 && v < 0.1) return '<0.1%';
  return v.toFixed(d) + '%';
};
const esc = s => (s == null ? '' : String(s).replace(/[&<>"'/]/g,
  c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;', '/': '&#47;' }[c])));

function starHTML(n) {
  const full = Math.max(0, Math.min(5, Math.round(n || 0)));
  return `<span class="stars">${'★'.repeat(full)}<span class="off">${'★'.repeat(5 - full)}</span></span>`;
}
function flagHTML(url, cls, alt) {
  // No inline onerror handler (our CSP blocks inline JS): a delegated 'error'
  // listener in boot() swaps a failed flag image for the data-fb text fallback.
  const fb = esc((alt || '').slice(0, 3).toUpperCase());
  if (url) return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt || '')}" data-fb="${fb}" loading="lazy" decoding="async" />`;
  return `<span class="${cls} noflag">${fb}</span>`;
}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200);
}

// ----- live-update primitives --------------------------------------------
// Honour reduced-motion everywhere: tweens/flashes degrade to an instant set.
const REDUCE_MOTION = matchMedia('(prefers-reduced-motion: reduce)').matches;

// Formatters a tweened number can render through. The element stores its target
// underlying value in data-num and the formatter key in data-fmt; the tween
// walks the underlying value (e.g. a 0–1 probability) and re-formats each frame
// so a "23.1%" counts up honestly rather than lerping the printed string.
const FMT = {
  pct:    v => pct(v, 1),
  pct0:   v => pct(v, 0),
  pctint: v => Math.round(v) + '%',     // value already on a 0–100 scale
  int:    v => Math.round(v).toLocaleString(),
  g1:     v => v.toFixed(1),
  g2:     v => v.toFixed(2),
};
// Count a number element from its current value to el.dataset.num. No-op (sets
// straight to target) under reduced-motion or for tiny deltas.
function tweenNum(el, from) {
  const to = parseFloat(el.dataset.num);
  const fmt = FMT[el.dataset.fmt] || FMT.int;
  if (!isFinite(to)) return;
  if (from == null || !isFinite(from)) from = to;
  if (REDUCE_MOTION || Math.abs(to - from) < 1e-9) { el.textContent = fmt(to); return; }
  const t0 = performance.now(), DUR = 620;
  cancelAnimationFrame(el._raf || 0);
  const step = now => {
    const k = Math.min(1, (now - t0) / DUR);
    const e = 1 - Math.pow(1 - k, 3);                 // easeOutCubic
    el.textContent = fmt(from + (to - from) * e);
    if (k < 1) el._raf = requestAnimationFrame(step);
  };
  el._raf = requestAnimationFrame(step);
}
// Brief highlight on a value that just changed.
function flash(el) {
  if (!el || REDUCE_MOTION) return;
  el.classList.remove('lv-flash');
  void el.offsetWidth;                                // restart the animation
  el.classList.add('lv-flash');
}

// Keyed in-place update. Repeating rows carry data-mk="<stable key>"; on a
// refresh we reconcile by key instead of replacing innerHTML wholesale — so the
// numbers count up (tweenNum), changed rows flash, focus/scroll survive and
// nothing flickers. Falls back to a plain swap when keys are absent or the set
// of keys changed wholesale (e.g. a fixture moved from upcoming → results).
function morph(host, html) {
  if (!host) return;
  if (!host.dataset.morph) { host.innerHTML = html; host.dataset.morph = '1'; return; }
  const tpl = document.createElement('div'); tpl.innerHTML = html;
  const newRows = [...tpl.children];
  const keyed = newRows.length && newRows.every(n => n.dataset.mk);
  const oldKeyed = [...host.children].every(n => n.dataset.mk);
  if (!keyed || !oldKeyed) { host.innerHTML = html; return; }
  const oldMap = new Map([...host.children].map(n => [n.dataset.mk, n]));
  const newKeys = new Set(newRows.map(n => n.dataset.mk));
  // drop rows that no longer exist
  for (const [k, n] of oldMap) if (!newKeys.has(k)) n.remove();
  let prev = null;
  for (const nn of newRows) {
    const k = nn.dataset.mk, old = oldMap.get(k);
    if (old) { morphRow(old, nn); place(host, old, prev); prev = old; }
    else { nn.classList.add('lv-enter'); place(host, nn, prev); prev = nn; }
  }
}
function place(host, node, prev) {
  const ref = prev ? prev.nextSibling : host.firstChild;
  if (node !== ref) host.insertBefore(node, ref);
}
// Reconcile one surviving row: capture old underlying values, adopt the new
// markup (labels/bars/classes), then tween each number from its old value and
// flash the row if anything actually changed.
function morphRow(oldEl, newEl) {
  if (oldEl.isEqualNode(newEl)) return;
  const oldNums = [...oldEl.querySelectorAll('[data-num]')].map(n => parseFloat(n.dataset.num));
  const wasOpen = oldEl.classList.contains('open');
  oldEl.innerHTML = newEl.innerHTML;
  // copy attributes (class/style/aria) but keep an expanded card expanded
  for (const a of [...oldEl.attributes]) if (!newEl.hasAttribute(a.name)) oldEl.removeAttribute(a.name);
  for (const a of [...newEl.attributes]) oldEl.setAttribute(a.name, a.value);
  if (wasOpen) { oldEl.classList.add('open'); oldEl.setAttribute('aria-expanded', 'true'); }
  [...oldEl.querySelectorAll('[data-num]')].forEach((n, i) => tweenNum(n, oldNums[i]));
  flash(oldEl);
}
const paint = (sel, html) => { const h = $(sel); if (h) morph(h, html); };

// ----- live match state ---------------------------------------------------
// The engine has no "in-play" flag: a match that has kicked off but isn't
// scored yet still sits in `upcoming` with a past `kickoff`. We derive the
// phase on the client. A football match (90' + half-time + stoppage) is treated
// as live for ~125 min after kickoff; after that an unscored tie is "awaiting"
// the result feed rather than implied still-playing.
const LIVE_MS = 125 * 60 * 1000;
const SOON_MS = 60 * 60 * 1000;
function matchPhase(m, now = Date.now()) {
  const ko = m.kickoff ? Date.parse(m.kickoff) : NaN;
  if (!isFinite(ko)) return { phase: 'pre', ko: NaN };
  const dt = now - ko;
  if (dt < 0) return { phase: dt > -SOON_MS ? 'soon' : 'pre', ko, ms: -dt };
  if (dt < LIVE_MS) return { phase: 'live', ko, ms: dt, minute: Math.max(1, Math.floor(dt / 60000)) };
  return { phase: 'await', ko, ms: dt };
}
// every live fixture from a fixtures payload, soonest kickoff first
function liveFixtures(fx) {
  return (fx?.upcoming || []).filter(m => matchPhase(m).phase === 'live')
    .sort((a, b) => Date.parse(a.kickoff) - Date.parse(b.kickoff));
}

// ----- shared state -------------------------------------------------------
const STATE = { meta: null, report: null, static: false };

// On a static (CDN) build there's no live engine: the Match Lab, the rankings
// trajectories and the intel filter read frozen snapshot files instead. These
// loaders are lazy + cached so a visitor only pays for what they open.
let _MATRIX = null, _HISTORY = null;
const loadMatrix = () => (_MATRIX ||= API('/api/predict_matrix.json'));
const loadHistory = () => (_HISTORY ||= API('/api/history.json'));

// Build a team sticker-card from the meta field list (same shape the live
// /api/predict returns for home_card/away_card).
function teamCard(name) {
  const f = (STATE.meta?.field || []).find(x => x.team === name);
  return f
    ? { team: name, elo: f.elo, stars: f.stars, flag: f.flag, iso2: f.iso2,
        confed: f.confed, confed_color: f.confed_color }
    : { team: name, elo: 1500, stars: 2.5, flag: null };
}
async function predictFromMatrix(home, away, neutral) {
  const m = await loadMatrix().catch(() => null);
  const e = m && m[`${home}|${away}|${neutral ? 1 : 0}`];
  if (!e) return { error: 'prediction not in the offline set' };
  return {
    home, away, neutral, p_home: e.ph, p_draw: e.pd, p_away: e.pa,
    exp_home_goals: e.xgh, exp_away_goals: e.xga,
    top_scoreline: e.ts, top_scorelines: e.tsl,
    home_card: teamCard(home), away_card: teamCard(away),
  };
}

// =========================================================================
//  COVER + META
// =========================================================================
function renderMeta(m) {
  STATE.meta = m;
  STATE.static = !!m.static;
  const c = m.counts || {};
  if (c.matches) $('#coverMatches').textContent = Number(c.matches).toLocaleString();

  // host badges
  $('#coverHosts').innerHTML = (m.hosts || []).map(h =>
    `<span class="host">${flagHTML(m.host_flags?.[h], 'flag-sm', h)} ${esc(h)}</span>`).join('');

  // stat stamps
  const acc = m.accuracy || {};
  const stamps = [
    ['gold', m.n_teams || 48, 'TEAMS'],
    ['navy', m.n_matches_tournament || 104, 'MATCHES'],
    ['teal', (m.last_sim?.runs ? Number(m.last_sim.runs).toLocaleString() : '50,000'), 'SIMS'],
    ['', acc.rps ?? '0.167', 'HELD-OUT RPS'],
  ];
  $('#coverStamps').innerHTML = stamps.map(([k, big, lbl]) =>
    `<div class="stamp ${k}"><b>${esc(big)}</b>${esc(lbl)}</div>`).join('');

  // footer meta
  $('#footMeta').textContent =
    `${(c.matches || 0).toLocaleString()} matches · ${c.rated_teams || 0} rated teams · `
    + `${c.news || 0} intel clippings · generated ${m.generated || ''}`;

  // pickers + intel filter
  const field = (m.field || []).slice().sort((a, b) => a.team.localeCompare(b.team));
  const opts = field.map(f => `<option value="${esc(f.team)}">${esc(f.team)}</option>`).join('');
  $('#pickHome').innerHTML = opts; $('#pickAway').innerHTML = opts;
  $('#pickHome').value = 'Argentina';
  $('#pickAway').value = field.some(f => f.team === 'Spain') ? 'Spain' : field[1]?.team;
  $('#intelTeam').innerHTML = '<option value="">All nations</option>' + opts;
}

// =========================================================================
//  TITLE ODDS  (podium + ranked bars + road-to-final pips)
// =========================================================================
function relTime(iso) {
  if (!iso) return '';
  const then = new Date(iso), mins = Math.round((Date.now() - then) / 60000);
  if (mins < 2) return 'just now';
  if (mins < 60) return mins + ' min ago';
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return hrs + (hrs === 1 ? ' hour ago' : ' hours ago');
  const days = Math.round(hrs / 24);
  return days + (days === 1 ? ' day ago' : ' days ago');
}
function renderOdds(rep) {
  STATE.report = rep;
  const odds = rep.title_odds || [];
  if (rep.runs) { $('#oddsRuns').textContent = Number(rep.runs).toLocaleString(); }
  if (rep.generated) {
    const f = $('#oddsFresh');
    if (f) f.textContent = `Model last refreshed ${relTime(rep.generated)}.`;
  }
  const maxWin = Math.max(...odds.map(o => o.p_win), 0.01);

  // podium (top 3)
  const medals = ['①', '②', '③'];
  paint('#podium', odds.slice(0, 3).map((o, i) => `
    <div class="pod pod-${i + 1}" data-mk="${esc(o.team)}">
      <div class="sticker foil tape">
        <div class="medal">${medals[i]}</div>
        ${flagHTML(o.flag, 'flag', o.team)}
        <div class="pod-team">${esc(o.team)}</div>
        <div class="pod-win"><span data-num="${o.p_win}" data-fmt="pct">${pct(o.p_win)}</span></div>
        <div class="pod-sub">final ${pct(o.p_final)} · semi ${pct(o.p_semi)}</div>
      </div>
    </div>`).join(''));

  // (The cover no longer reveals the favourite — the winner is the payoff of
  // "The Whole" mural, not a spoiler on the front page.)

  // full ranked list
  paint('#oddsList', odds.map((o, i) => {
    const w = Math.max(2, (o.p_win / maxWin) * 100);
    const pip = (v, cls = '') => `<span class="pip ${cls}" style="height:${Math.max(3, (v || 0) * 24)}px" title="${pct(v)}"></span>`;
    return `
      <div class="odds-row profile-link" data-mk="${esc(o.team)}" data-team="${esc(o.team)}" role="button" tabindex="0" aria-label="Open ${esc(o.team)} profile">
        <span class="orank">${i + 1}</span>
        ${flagHTML(o.flag, 'flag-sm', o.team)}
        <div class="obar-wrap">
          <span class="oteam">${esc(o.team)}</span>
          <div class="obar" style="width:${w}%;background:${o.confed_color || 'var(--gold)'}"></div>
        </div>
        <div style="display:flex;align-items:center;gap:14px">
          <div class="road" title="QF / SF / Final / Win">
            ${pip(o.p_quarter)}${pip(o.p_semi)}${pip(o.p_final, 'f')}${pip(o.p_win, 'w')}
          </div>
          <span class="owin" data-num="${o.p_win}" data-fmt="pct">${pct(o.p_win)}</span>
        </div>
      </div>`;
  }).join(''));
}

// =========================================================================
//  WALLCHART (bracket)
// =========================================================================
function slot(card, isWin, seed) {
  return `<div class="slot ${isWin ? 'win' : 'out'}">
      ${seed ? `<span class="seed">${esc(seed)}</span>` : ''}
      ${flagHTML(card.flag, 'flag-xs', card.team)}
      <span class="nm">${esc(card.team)}</span>
    </div>`;
}
function tieHTML(t, seeds) {
  return `<div class="tie">
    ${slot(t.a, t.winner === t.a.team, seeds ? t.slot1 : '')}
    ${slot(t.b, t.winner === t.b.team, seeds ? t.slot2 : '')}
  </div>`;
}
function renderBracket(b) {
  if (b.error) { $('#bracket').innerHTML = `<p class="loading">${esc(b.error)}</p>`; return; }
  const col = (title, html) => `<div class="col"><div class="col-title">${title}</div>${html}</div>`;
  const r32a = b.r32.slice(0, 8), r32b = b.r32.slice(8);
  const R = b.rounds;
  const half = (arr, a, z) => arr.slice(a, z).map(t => tieHTML(t)).join('');

  $('#bracket').innerHTML =
    col('R32 ·  ½', r32a.map(t => tieHTML(t, true)).join('')) +
    col('R16', half(R.r16, 0, 4)) +
    col('QF', half(R.qf, 0, 2)) +
    col('SEMI', half(R.sf, 0, 1)) +
    `<div class="col champ-col">
        <div class="champ">
          <div class="lbl">CHAMPION ’26</div>
          <div class="trophy">🏆</div>
          ${flagHTML(b.champion.flag, 'flag', b.champion.team)}
          <div class="nm">${esc(b.champion.team)}</div>
          <div class="muted" style="font-size:.78rem">${pct(b.champion.p_win)} title odds</div>
        </div>
        <div class="col-title" style="margin-top:14px">FINAL</div>
        ${R.final.map(t => tieHTML(t)).join('')}
      </div>` +
    col('SEMI', half(R.sf, 1, 2)) +
    col('QF', half(R.qf, 2, 4)) +
    col('R16', half(R.r16, 4, 8)) +
    col('R32 ·  ½', r32b.map(t => tieHTML(t, true)).join(''));

  $('#bracketNote').textContent = b.note || '';
}

// =========================================================================
//  GROUPS
// =========================================================================
function renderGroups(g) {
  if (g.error) { $('#groupsGrid').innerHTML = `<p class="loading">${esc(g.error)}</p>`; return; }
  // toughest group = highest combined Elo of its top three sides
  let death = null, best = -1;
  for (const k of Object.keys(g)) {
    const top3 = g[k].slice(0, 3).reduce((s, t) => s + (t.elo || 0), 0);
    if (top3 > best) { best = top3; death = k; }
  }
  const rots = [-1, .8, -.6, 1, -.9, .5];
  paint('#groupsGrid', Object.keys(g).sort().map((k, gi) => {
    const rows = g[k].map((t, i) => `
      <div class="grow profile-link" data-team="${esc(t.team)}" role="button" tabindex="0" aria-label="Open ${esc(t.team)} profile">
        <span class="gpos">${i + 1}</span>
        ${flagHTML(t.flag, 'flag-sm', t.team)}
        <span class="gnm">${esc(t.team)}<small>Elo ${Math.round(t.elo)} · ${esc(t.confed)}</small></span>
        <div class="advwrap">
          <div class="advbar"><span style="width:${t.adv}%;background:${t.adv >= 60 ? 'var(--teal)' : t.adv >= 35 ? 'var(--gold)' : 'var(--red)'}"></span></div>
          <span class="advpct" data-num="${t.adv}" data-fmt="pctint">${t.adv}%</span>
        </div>
      </div>`).join('');
    return `<div class="group-card" data-mk="${esc(k)}" style="--rot:${rots[gi % rots.length]}deg">
      <div class="gc-head">
        <span class="gname">Group ${k}</span>
        ${k === death ? '<span class="gtag death">💀 Group of Death</span>'
                      : '<span class="gtag">Adv%</span>'}
      </div>${rows}</div>`;
  }).join(''));
}

// =========================================================================
//  POWER RANKINGS  (+ click-to-expand Elo trajectory sparkline)
// =========================================================================
function sparkline(series) {
  if (!series || series.length < 2) return '<div class="muted">no history</div>';
  const xs = series.map((_, i) => i), ys = series.map(p => p[1]);
  const mn = Math.min(...ys), mx = Math.max(...ys), W = 300, H = 90, pad = 6;
  const X = i => pad + (i / (xs.length - 1)) * (W - 2 * pad);
  const Y = v => H - pad - ((v - mn) / Math.max(1, mx - mn)) * (H - 2 * pad);
  const d = series.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ');
  const area = `M${X(0)},${H - pad} ` + series.map((p, i) => `L${X(i).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(' ') + ` L${X(xs.length - 1)},${H - pad} Z`;
  const first = series[0][0]?.slice(0, 4), last = series[series.length - 1][0]?.slice(0, 4);
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <path d="${area}" fill="rgba(227,165,18,.18)"/>
      <path d="${d}" fill="none" stroke="var(--gold-deep)" stroke-width="2.5" stroke-linejoin="round"/>
      <circle cx="${X(xs.length - 1)}" cy="${Y(ys[ys.length - 1])}" r="3.5" fill="var(--terra)" stroke="var(--card-edge)"/>
    </svg>
    <div class="rc-meta"><span>${first}</span><span>peak ${Math.round(mx)}</span><span>${last}</span></div>`;
}
// Expand/collapse a rank card's Elo-trajectory sparkline (shared by click + key).
async function expandRank(card) {
  const open = card.classList.toggle('open');
  card.setAttribute('aria-expanded', open ? 'true' : 'false');
  const box = $('.spark', card);
  if (open && !box.dataset.loaded) {
    box.innerHTML = '<div class="muted">loading trajectory…</div>';
    try {
      const series = STATE.static
        ? (await loadHistory())[card.dataset.team]
        : (await API(`/api/history?team=${encodeURIComponent(card.dataset.team)}`)).series;
      box.innerHTML = series ? sparkline(series) : '<div class="muted">no history</div>';
      box.dataset.loaded = '1';
    } catch (e) { box.innerHTML = '<div class="muted">history unavailable</div>'; }
  }
}
function renderRankings(data) {
  const rows = data.rankings || [];
  STATE.rankings = rows;                       // cached for the team profile (attack/defence/rank)
  $('#rankBoard').innerHTML = rows.map(r => `
    <div class="rank-card ${r.rank <= 3 ? 'top3' : ''}" data-team="${esc(r.team)}"
         tabindex="0" role="button" aria-expanded="false"
         aria-label="${esc(r.team)} — show Elo rating trajectory">
      <div class="rc-top">
        <span class="rc-rank">${r.rank}</span>
        ${flagHTML(r.flag, 'flag-sm', r.team)}
        <span class="rc-name">${esc(r.team)}</span>
        <span class="rc-elo">${Math.round(r.elo)}</span>
      </div>
      <div class="rc-meta">
        ${starHTML(r.stars)}
        <span class="chip" style="background:${r.confed_color};color:#fff">${esc(r.confed)}</span>
        ${r.in_field ? '<span class="chip" style="background:var(--teal);color:#fff">WC ’26</span>' : '<span class="chip muted">—</span>'}
      </div>
      <div class="spark"></div>
    </div>`).join('');

  $$('.rank-card').forEach(card => {
    card.addEventListener('click', () => expandRank(card));
    card.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); expandRank(card); }
    });
  });
}

// =========================================================================
//  MATCH LAB (live predictor)
// =========================================================================
async function runPredict() {
  const home = $('#pickHome').value, away = $('#pickAway').value;
  const neutral = $('#neutralChk').checked ? 1 : 0;
  if (!home || !away || home === away) {
    $('#tale').innerHTML = '<p class="loading">pick two different teams</p>'; return;
  }
  $('#tale').innerHTML = '<p class="loading">running the ensemble…</p>';
  let r;
  try {
    r = STATE.static
      ? await predictFromMatrix(home, away, $('#neutralChk').checked)
      : await API(`/api/predict?home=${encodeURIComponent(home)}&away=${encodeURIComponent(away)}&neutral=${neutral}`);
  } catch (e) { $('#tale').innerHTML = '<p class="loading">prediction failed</p>'; return; }
  if (r.error) { $('#tale').innerHTML = `<p class="loading">${esc(r.error)}</p>`; return; }

  const H = r.home_card, A = r.away_card;
  const ph = r.p_home, pd = r.p_draw, pa = r.p_away;
  const venue = $('#neutralChk').checked ? 'neutral venue' : `${esc(home)} at home`;
  $('#tale').innerHTML = `
    <div class="tale-head">
      <div class="side">${flagHTML(H.flag, 'flag', home)}<div class="tnm">${esc(home)}</div><div class="telo">Elo ${Math.round(H.elo)} ${starHTML(H.stars)}</div></div>
      <div class="vs">VS</div>
      <div class="side">${flagHTML(A.flag, 'flag', away)}<div class="tnm">${esc(away)}</div><div class="telo">Elo ${Math.round(A.elo)} ${starHTML(A.stars)}</div></div>
    </div>
    <div class="split">
      <div class="s-home" style="width:${ph * 100}%">${ph > .08 ? pct(ph, 0) : ''}</div>
      <div class="s-draw" style="width:${pd * 100}%">${pd > .08 ? pct(pd, 0) : ''}</div>
      <div class="s-away" style="width:${pa * 100}%">${pa > .08 ? pct(pa, 0) : ''}</div>
    </div>
    <div class="split-legend"><span>${esc(home)} win</span><span>draw</span><span>${esc(away)} win</span></div>
    <div class="tale-stats">
      <div class="tstat"><div class="lbl">Expected goals</div><div class="val">${r.exp_home_goals.toFixed(2)}<small> – </small>${r.exp_away_goals.toFixed(2)}</div></div>
      <div class="tstat"><div class="lbl">Most likely score</div><div class="val">${esc(r.top_scoreline)}</div></div>
      <div class="tstat"><div class="lbl">Venue</div><div class="val" style="font-size:1rem;font-family:var(--font-lab)">${venue}</div></div>
    </div>
    <div class="scorelines">
      ${(r.top_scorelines || []).map((s, i) => `<div class="sl-chip ${i === 0 ? 'best' : ''}">${esc(s.score)} <small>${pct(s.p, 1)}</small></div>`).join('')}
    </div>`;
}

// =========================================================================
//  INTEL FEED
// =========================================================================
function renderNews(data) {
  const items = data.news || [];
  if (!data.team && items.length) STATE.newsAll = items;   // keep the full feed for offline filtering
  if (!items.length) { $('#clippings').innerHTML = '<p class="loading">no clippings tagged for this nation yet.</p>'; return; }
  const rots = [-1.2, .9, -.5, 1.1, -.8, .6, -1];
  $('#clippings').innerHTML = items.map((n, i) => {
    const when = n.published ? new Date(n.published).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) : '';
    const tags = (n.flags || []).map(f => `<span class="tag ${esc(f)}">${esc(f)}</span>`).join('');
    const flags = Object.entries(n.team_flags || {}).slice(0, 4)
      .map(([t, u]) => flagHTML(u, 'flag-xs', t)).join('');
    return `<div class="clip" style="--rot:${rots[i % rots.length]}deg">
        <div class="clip-src"><span>${esc(n.source)}</span><span>${esc(when)}</span></div>
        <div class="clip-title">${esc(n.title)}</div>
        <div class="clip-foot">${tags}<span class="teams">${flags}</span></div>
      </div>`;
  }).join('');
}

// =========================================================================
//  METHOD
// =========================================================================
function renderMethod(m) {
  const a = m.accuracy || {};
  const metric = (k, v, good) => `<div class="metric-row"><span class="mk">${k}</span><span class="mv ${good ? 'good' : ''}">${v}</span></div>`;
  const srcs = [
    ['var(--teal)', 'martj42 / international_results', '49,378 matches since 1872 + shootouts'],
    ['var(--navy)', 'TheSportsDB', 'live 2026 fixtures, in-play & final scores'],
    ['var(--terra)', 'StatsBomb open data', 'shot-level expected goals (xG)'],
    ['var(--gold-deep)', 'BBC · Guardian · Sky · ESPN', 'RSS intel, auto-tagged & flagged'],
  ];
  const pipe = ['International Elo (tournament-weighted, GD multiplier)',
    'Dixon-Coles attack/defence (time-decayed MLE)',
    'Ordered-logit draw model + ensemble blend',
    'Calibration temperature (held-out fit)',
    'Monte-Carlo over the official bracket'];
  $('#method').innerHTML = `
    <div class="mcard">
      <h3>Held-out accuracy</h3>
      ${metric('Ranked Probability Score', (a.rps ?? '—'), true)}
      ${metric('Log-loss', (a.logloss ?? '—'), true)}
      ${metric('Brier score', (a.brier ?? '—'), false)}
      ${metric('Calibration error (ECE)', (a.ece ?? '—'), true)}
      ${metric('vs base-rate RPS', (a.baseline_rps ?? '—'), false)}
      <p class="muted" style="margin-top:10px;font-size:.82rem">Walk-forward, leakage-free over ${a.n ? a.n.toLocaleString() : '8,009'} internationals (${esc(a.window || '2018+')}). Beats the base-rate baseline by ~26% RPS.</p>
    </div>
    <div class="mcard">
      <h3>The pipeline</h3>
      <div class="pipeline">
        ${pipe.map((s, i) => `<div class="pipe-step"><span class="num">${i + 1}</span><span>${esc(s)}</span></div>`).join('')}
      </div>
    </div>
    <div class="mcard">
      <h3>Data sources</h3>
      <div class="src-list">
        ${srcs.map(([c, t, d]) => `<div class="src"><span class="sdot" style="background:${c}"></span><span><b>${esc(t)}</b><br><span class="muted" style="font-size:.82rem">${esc(d)}</span></span></div>`).join('')}
      </div>
    </div>`;
}

// =========================================================================
//  MATCH CENTRE  (fixtures + results, with the model's call)
// =========================================================================
const WK = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const MO = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
function fmtDate(iso) {
  const d = new Date(iso + 'T00:00:00');
  return `${WK[d.getDay()]} ${d.getDate()} ${MO[d.getMonth()]}`;
}
// Localise a UTC kickoff (ISO 8601) to the viewer's own clock: time, tz abbrev
// and their *local* calendar day (a late kickoff can land on a different day
// depending where in the world you are).
function fmtKick(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const day = `${WK[d.getDay()]} ${d.getDate()} ${MO[d.getMonth()]}`;
  let tz = '';
  try {
    tz = new Intl.DateTimeFormat([], { timeZoneName: 'short' })
           .formatToParts(d).find(p => p.type === 'timeZoneName')?.value || '';
  } catch (e) { /* no Intl — skip the zone label */ }
  return { time, tz, day, ms: d.getTime() };
}
// chronological sort key — real kickoff if known, else the listed date at UTC midnight
const kickMs = m => m.kickoff ? Date.parse(m.kickoff) : Date.parse(m.date + 'T00:00:00Z');
// mini win/draw/win bar used in fixture rows
function wdwBar(ph, pd, pa, fav) {
  const seg = (cls, v, on) => `<span class="wdw-seg ${cls} ${on ? 'on' : ''}" style="width:${(v * 100).toFixed(1)}%">${v > .14 ? pct(v, 0) : ''}</span>`;
  return `<div class="wdw">${seg('h', ph, fav === 'home')}${seg('d', pd, fav === 'draw')}${seg('a', pa, fav === 'away')}</div>`;
}
function mcSide(card, side, isFav, isWin) {
  const cls = `mc-side ${side}` + (isFav ? ' fav' : '') + (isWin === true ? ' won' : isWin === false ? ' lost' : '');
  const elo = `<span class="mc-elo">${Math.round(card.elo)}</span>`;
  const nm = `<span class="mc-nm">${esc(card.team)}</span>`;
  const fl = flagHTML(card.flag, 'flag-sm', card.team);
  return `<div class="${cls}">${side === 'home' ? fl + nm + elo : elo + nm + fl}</div>`;
}
// The "when" cell for an upcoming tie: a pulsing LIVE clock once it has kicked
// off (minute ticked by the live ticker), an "● kicks off soon" flag in the last
// hour, an "awaiting result" note once it's run long past kickoff, else the
// localised kickoff time.
function mcWhen(m) {
  const ph = matchPhase(m);
  if (ph.phase === 'live')
    return `<div class="mc-kick mc-live"><span class="livedot"></span>LIVE <b data-live-start="${esc(m.kickoff)}">${ph.minute}'</b></div>`;
  if (ph.phase === 'await')
    return `<div class="mc-kick mc-await">FT? <small>awaiting result</small></div>`;
  const k = fmtKick(m.kickoff);
  if (ph.phase === 'soon' && k)
    return `<div class="mc-kick mc-soon"><span class="livedot"></span>${k.time}<small>${esc(k.tz)}</small></div>`;
  return k ? `<div class="mc-kick">${k.time}<small>${esc(k.tz)}</small></div>` : '';
}

function mcCard(m, done) {
  const favHome = m.fav === 'home', favAway = m.fav === 'away';
  const mk = `data-mk="${esc(m.home.team)}|${esc(m.away.team)}"`;
  let mid;
  if (done) {
    const winH = m.actual === 'home', winA = m.actual === 'away';
    const stamp = m.called
      ? '<span class="mc-stamp ok">✓ called</span>'
      : '<span class="mc-stamp miss">✗ missed</span>';
    mid = `<div class="mc-mid">
        <div class="mc-score">${m.home_score}<span>–</span>${m.away_score}</div>
        ${stamp}
        <div class="mc-line">model: ${wdwLabel(m)}</div>
      </div>`;
    return `<div class="mc-card done" ${mk}>
        <div class="mc-date">${fmtDate(m.date)}</div>
        ${mcSide(m.home, 'home', favHome, winH ? true : winA ? false : null)}
        ${mid}
        ${mcSide(m.away, 'away', favAway, winA ? true : winH ? false : null)}
      </div>`;
  }
  const phase = matchPhase(m).phase;                         // pre · soon · live · await
  mid = `<div class="mc-mid">
      ${mcWhen(m)}
      ${wdwBar(m.p_home, m.p_draw, m.p_away, m.fav)}
      <div class="mc-line">xG ${m.exp_home_goals.toFixed(1)}–${m.exp_away_goals.toFixed(1)} · likely <b>${esc(m.top_scoreline)}</b>${m.neutral ? '' : ' · home adv'}</div>
    </div>`;
  return `<div class="mc-card ${phase === 'live' ? 'is-live' : phase === 'soon' ? 'is-soon' : ''}" ${mk}>
      <div class="mc-date">${fmtDate(m.date)}</div>
      ${mcSide(m.home, 'home', favHome)}
      ${mid}
      ${mcSide(m.away, 'away', favAway)}
    </div>`;
}
function wdwLabel(m) {
  const lab = m.fav === 'draw' ? 'draw' : m.fav === 'home' ? esc(m.home.team) : esc(m.away.team);
  const p = Math.max(m.p_home, m.p_draw, m.p_away);
  return `${lab} ${pct(p, 0)}`;
}
function renderFixtures(data) {
  STATE.fixtures = data;
  if (data.error) { $('#mcList').innerHTML = `<p class="loading">${esc(data.error)}</p>`; return; }
  renderKickoff(data.kickoff);
  const rec = data.record || {};
  const recEl = $('#mcRecord');
  if (rec.played) {
    recEl.innerHTML = `Model record so far: <span class="rec-num">${rec.called}/${rec.played}</span> (${pct(rec.pct, 0)}) called.`;
  } else {
    recEl.textContent = `Kicks off ${fmtDate(data.kickoff)}.`;
  }
  $('#mcTabDone').textContent = `Results${rec.played ? ' (' + rec.played + ')' : ''}`;
  $('#mcTabUp').textContent = `Upcoming${data.upcoming?.length ? ' (' + data.upcoming.length + ')' : ''}`;
  // default to results once any exist, else upcoming — but while a match is in
  // play, open on Upcoming so the live action is front-and-centre.
  if (!STATE.mcTab) STATE.mcTab = liveFixtures(data).length ? 'upcoming' : (rec.played ? 'completed' : 'upcoming');
  paintFixtures();
}
function paintFixtures() {
  const data = STATE.fixtures; if (!data) return;
  const tab = STATE.mcTab;
  $$('.mc-tab').forEach(b => {
    const on = b.dataset.mc === tab;
    b.classList.toggle('active', on);
    b.setAttribute('aria-selected', on ? 'true' : 'false');
  });
  const completedTab = tab === 'completed';
  // Any match that has kicked off but isn't scored yet is pinned to the top of
  // the list under a LIVE banner — shown on EITHER tab so a match in play is
  // never hidden — and pulled out of the day grouping so it never shows twice.
  const live = liveFixtures(data);
  const liveSet = new Set(live.map(m => m.home.team + '|' + m.away.team));
  // Upcoming reads forward in time; Results reads backward (latest at the top —
  // with 104 matches over five weeks nobody scrolls for last night's score).
  const base = [...((completedTab ? data.completed : data.upcoming) || [])]
    .filter(m => !liveSet.has(m.home.team + '|' + m.away.team))
    .sort((a, b) => completedTab ? kickMs(b) - kickMs(a) : kickMs(a) - kickMs(b));

  if (!base.length && !live.length) {
    $('#mcList').innerHTML = `<p class="loading">${completedTab
      ? 'No results yet — the tournament hasn\'t kicked off. Check back from ' + fmtDate(data.kickoff) + '.'
      : 'No upcoming fixtures scheduled.'}</p>`;
    return;
  }
  let html = '';
  if (live.length) {
    html += `<div class="mc-day mc-day-live"><span class="livedot"></span>LIVE NOW · ${live.length} match${live.length > 1 ? 'es' : ''} underway</div>`;
    html += live.map(m => mcCard(m, false)).join('');
  }
  // group by the viewer's LOCAL day (a late kickoff can fall on a different
  // calendar day depending where in the world you are), with a day header
  let day = null;
  for (const m of base) {
    const k = fmtKick(m.kickoff);
    const label = k ? k.day : fmtDate(m.date);
    if (label !== day) { day = label; html += `<div class="mc-day">${label}</div>`; }
    html += mcCard(m, completedTab);
  }
  $('#mcList').innerHTML = html;
  syncLivePill();
}

// =========================================================================
//  COVER KICKOFF BADGE  (countdown → live → done)
// =========================================================================
function renderKickoff(kickoffISO) {
  const el = $('#coverKickoff'); if (!el) return;
  const start = new Date((kickoffISO || '2026-06-11') + 'T00:00:00');
  const now = new Date();
  const days = Math.ceil((start - now) / 86400000);
  let txt;
  if (days > 1) txt = `<span class="ko-n">${days}</span> DAYS TO KICKOFF`;
  else if (days === 1) txt = `KICKS OFF <span class="ko-n">TOMORROW</span>`;
  else if (days === 0) txt = `<span class="ko-live">● LIVE</span> KICKOFF TODAY`;
  else txt = `<span class="ko-live">● LIVE</span> TOURNAMENT UNDERWAY`;
  el.innerHTML = `<div class="kickoff-badge">${txt}</div>`;
}

// =========================================================================
//  TOPBAR WORLD CLOCK  — the viewer's own local time, ticking to the second
// =========================================================================
function startClock() {
  const el = $('#worldClock'); if (!el) return;
  const tEl = el.querySelector('.wc-time'), zEl = el.querySelector('.wc-zone');
  try {
    const parts = new Intl.DateTimeFormat([], { timeZoneName: 'short' }).formatToParts(new Date());
    if (zEl) zEl.textContent = parts.find(p => p.type === 'timeZoneName')?.value || '';
    el.title = 'Your local time · ' + (Intl.DateTimeFormat().resolvedOptions().timeZone || 'local');
  } catch (e) { /* ancient browser without Intl — leave the zone label blank */ }
  const two = n => String(n).padStart(2, '0');
  const tick = () => {
    const d = new Date();
    if (tEl) tEl.textContent = `${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}`;
    el.setAttribute('datetime', d.toISOString());
  };
  tick();
  // align the first interval to the next whole second so the flip lands cleanly
  clearTimeout(startClock._t); clearInterval(startClock._i);
  startClock._t = setTimeout(() => { tick(); startClock._i = setInterval(tick, 1000); },
                             1000 - (Date.now() % 1000));
}

// =========================================================================
//  MONETISATION LINKS  —  ⚙️ paste your real URLs here (see LAUNCH.md)
// =========================================================================
// Lean & legal: a tip jar + an optional "back the project" button. No
// bookmaker/betting links (AU Interactive Gambling Act). Leave a value '' to
// hide that button.
const LINKS = {
  tip:  'https://ko-fi.com/sambowey1110',              // Ko-fi tip jar (LIVE)
  back: 'https://buy.stripe.com/dRm28s8AI8y0al7dan9k400',  // Stripe Payment Link (LIVE — a public, shareable URL; safe to embed. No secret/pk keys ever live here.)
};
function wireSupport() {
  const tip = $('#tipBtn'), back = $('#backBtn');
  if (tip && LINKS.tip && !LINKS.tip.includes('YOUR_')) tip.href = LINKS.tip;
  if (back && LINKS.back && !LINKS.back.includes('YOUR_')) { back.href = LINKS.back; back.hidden = false; }
}

// =========================================================================
//  SHARE
// =========================================================================
async function doShare() {
  const url = location.origin + '/';
  const shareData = {
    title: 'WCPA — World Cup ’26 Prediction Album',
    text: 'Every World Cup ’26 match called by a backtested model, in a retro sticker album.',
    url,
  };
  try {
    if (navigator.share) { await navigator.share(shareData); return; }
  } catch (e) { /* user cancelled — fall through to copy */ }
  try {
    await navigator.clipboard.writeText(url);
    toast('link copied — share the album ⚽');
  } catch (e) { toast(url); }
}

// =========================================================================
//  SCROLLSPY (active album-index link)
// =========================================================================
function scrollspy() {
  const links = $$('.album-index a');
  const map = {}; links.forEach(a => map[a.getAttribute('href').slice(1)] = a);
  const obs = new IntersectionObserver(entries => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        links.forEach(l => { l.classList.remove('active'); l.removeAttribute('aria-current'); });
        const a = map[e.target.id];
        if (a) { a.classList.add('active'); a.setAttribute('aria-current', 'true'); }
      }
    });
  }, { rootMargin: '-45% 0px -50% 0px' });
  // observe exactly the sections the nav links to — never drifts from the markup
  Object.keys(map).forEach(id => { const s = document.getElementById(id); if (s) obs.observe(s); });
}

// =========================================================================
//  POLISH  —  loading skeletons, scroll progress, reveal-on-scroll
// =========================================================================
const sk = (n, cls = 'sk-row') =>
  Array.from({ length: n }, () => `<div class="${cls} skeleton"></div>`).join('');
function skeletonFill() {
  const set = (sel, html) => { const e = $(sel); if (e) e.innerHTML = html; };
  set('#oddsList', sk(8, 'sk-row'));
  set('#mcList', sk(4, 'sk-card'));
  set('#groupsGrid', sk(6, 'sk-card'));
  set('#rankBoard', sk(8, 'sk-card'));
}
function initScrollProgress() {
  const bar = $('#scrollProgress'); if (!bar) return;
  const upd = () => {
    const h = document.documentElement;
    const max = h.scrollHeight - h.clientHeight;
    bar.style.width = (max > 0 ? (h.scrollTop / max) * 100 : 0) + '%';
  };
  document.addEventListener('scroll', upd, { passive: true });
  window.addEventListener('resize', upd); upd();
}
function initReveal() {
  // Progressive enhancement only: if motion is reduced or IO is missing, the
  // sections never get .will-reveal, so they stay fully visible.
  if (matchMedia('(prefers-reduced-motion: reduce)').matches || !('IntersectionObserver' in window)) return;
  const obs = new IntersectionObserver((entries, o) => {
    entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('revealed'); o.unobserve(e.target); } });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.04 });
  $$('main > section.page').forEach(s => { s.classList.add('will-reveal'); obs.observe(s); });
  // Safety net: whatever the observer hasn't reached after 3s, show anyway —
  // content must never stay hidden behind the animation.
  setTimeout(() => $$('.will-reveal').forEach(s => s.classList.add('revealed')), 3000);
}

// =========================================================================
//  DAILY TEAM THEME  —  the album wears a different nation's colours each day.
//  Highlights cascade because --gold / --terra / --red etc. are defined as
//  var(--accent) / var(--accent-2) in the CSS, so setting those two custom
//  properties re-themes the whole page. Today is pinned to Brazil × Morocco;
//  every other day is picked deterministically from the date (same palette for
//  everyone that day, and it rotates).
// =========================================================================
const TEAM_COLORS = {
  Brazil: ['#009C3B', '#FFDF00'], Argentina: ['#6CACE4', '#ffffff'], Spain: ['#C60B1E', '#FFC400'],
  France: ['#1E4DB7', '#EF4135'], England: ['#CE1124', '#ffffff'], Portugal: ['#C8102E', '#0B6E4F'],
  Germany: ['#E1140A', '#FFCE00'], Netherlands: ['#FF6A13', '#21468B'], Belgium: ['#C8102E', '#FDDA24'],
  Italy: ['#1B62C7', '#ffffff'], Croatia: ['#D7142B', '#2B4B9B'], Morocco: ['#C1272D', '#0B6E4F'],
  Mexico: ['#0B7A4B', '#CE1126'], 'United States': ['#1B3A8C', '#B31942'], Canada: ['#D52B1E', '#ffffff'],
  Uruguay: ['#4F9BD9', '#0A1A6B'], Colombia: ['#FCD116', '#C8102E'], Japan: ['#C8102E', '#ffffff'],
  'South Korea': ['#CD2E3A', '#0047A0'], Senegal: ['#0B8A43', '#E31B23'], Switzerland: ['#D52B1E', '#ffffff'],
  Denmark: ['#C60C30', '#ffffff'], Ecuador: ['#FFD100', '#0072CE'], Poland: ['#DC143C', '#ffffff'],
  Serbia: ['#C6363C', '#15467A'], Ghana: ['#0B7A3B', '#FCD116'], Nigeria: ['#0B8A4B', '#ffffff'],
  Cameroon: ['#0B7A5E', '#CE1126'], Australia: ['#0B8A3D', '#FFCD00'], 'Saudi Arabia': ['#0B7A3D', '#ffffff'],
  Iran: ['#239F40', '#DA0000'], Qatar: ['#8A1538', '#ffffff'], Egypt: ['#C8102E', '#ffffff'],
  Algeria: ['#0B7A3D', '#ffffff'], Tunisia: ['#E70013', '#ffffff'], Norway: ['#BA0C2F', '#1B3A8C'],
  Sweden: ['#1B62C7', '#FECC00'], Austria: ['#ED2939', '#ffffff'], Turkey: ['#E30A17', '#ffffff'],
  Ukraine: ['#FFD500', '#0057B7'], Wales: ['#C8102E', '#0B8A3D'], Scotland: ['#1666C2', '#ffffff'],
  Peru: ['#D91023', '#ffffff'], Chile: ['#1B49B5', '#DA291C'], Paraguay: ['#DA121A', '#0B43A8'],
  'Costa Rica': ['#1B49B5', '#CE1126'], Panama: ['#DA121A', '#0B5293'], Honduras: ['#1B83CF', '#ffffff'],
  Jamaica: ['#0B9B3A', '#FED100'], 'Ivory Coast': ['#FF8200', '#0B9A44'], Mali: ['#FCD116', '#16B53A'],
  'Cape Verde': ['#1B49B5', '#CF2027'], 'South Africa': ['#0B7A4D', '#FFB915'], 'DR Congo': ['#1B7FFF', '#F7D618'],
};
const THEME_FALLBACK = ['#d8b54a', '#2e9e7e'];
const THEME_PINS = { '2026-06-08': ['Brazil', 'Morocco'] };

function _todayKey(d) {
  d = d || new Date();
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}
function pickDailyTeams(key) {
  key = key || _todayKey();
  if (THEME_PINS[key]) return THEME_PINS[key].slice(0, 2);
  const teams = Object.keys(TEAM_COLORS);
  let h = 2166136261;                                   // FNV-1a over the date → stable per day
  for (let i = 0; i < key.length; i++) { h ^= key.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
  const a = h % teams.length;
  let b = (Math.imul(h ^ 0x9e3779b9, 2654435761) >>> 0) % teams.length;
  if (b === a) b = (b + 1) % teams.length;
  return [teams[a], teams[b]];
}
function applyDailyTheme() {
  const pair = pickDailyTeams();
  const ca = TEAM_COLORS[pair[0]] || THEME_FALLBACK;
  const cb = TEAM_COLORS[pair[1]] || THEME_FALLBACK;
  const root = document.documentElement;
  root.style.setProperty('--accent', ca[0]);
  root.style.setProperty('--accent-2', cb[0]);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute('content', '#141310');
  try {                                                 // a small credit on the cover (decorative — never blocks boot)
    const host = document.querySelector('.cover-inner');
    if (host && !document.querySelector('.theme-credit')) {
      const el = document.createElement('div');
      el.className = 'theme-credit';
      el.innerHTML =
        '<span class="tc-x">TODAY’S COLOURS</span>' +
        '<span class="tc-team"><i style="background:' + ca[0] + '"></i>' + pair[0] + '</span>' +
        '<span class="tc-x">×</span>' +
        '<span class="tc-team"><i style="background:' + cb[0] + '"></i>' + pair[1] + '</span>';
      const stamps = document.getElementById('coverStamps');
      host.insertBefore(el, stamps ? stamps.nextSibling : null);
    }
  } catch (e) { /* credit is decorative */ }
  return pair;
}

// =========================================================================
//  THE WHOLE  —  one living mural of the entire tournament (page 01, the funnel)
//  Fuses five existing feeds (no new endpoint): fixtures (pulse), groupadv
//  (funnel), bracket (knockout river), report (champion altar), news (intel).
// =========================================================================
let _WHOLE = null;
function ensureData() {
  // one cached Promise of every feed the mural + team profiles need
  if (_WHOLE) return _WHOLE;
  const get = (k, url, fb) => API(url).then(r => (STATE[k] = r)).catch(() => (STATE[k] = fb));
  _WHOLE = Promise.all([
    STATE.report ? Promise.resolve(STATE.report) : get('report', '/api/report.json', {}),
    get('groupadv', '/api/groupadv.json', {}),
    get('bracket', '/api/bracket.json', {}),
    get('fixtures', '/api/fixtures.json', {}),
    get('news', '/api/news.json', {}),
    get('media', '/api/team_media.json', {}),   // may not exist yet → {} → flag fallback
  ]).then(([report, groupadv, bracket, fixtures, news, media]) =>
    ({ report: STATE.report || report, groupadv, bracket, fixtures, news, media }));
  return _WHOLE;
}
const _field = t => (STATE.meta?.field || []).find(x => x.team === t) || {};

async function renderWhole() {
  let d;
  try { d = await ensureData(); }
  catch (e) { const l = $('#muralLoading'); if (l) l.textContent = 'the whole tournament is briefly unavailable.'; return; }
  muralPulse(d.fixtures); muralGroups(d.groupadv);
  $('#muralRiver').innerHTML = buildRiverSVG(d.bracket);
  muralAltar(d.report); muralIntel(d.news);
  const l = $('#muralLoading'); if (l) l.hidden = true;
  startMuralClock();
}

function muralPulse(fx) {
  const rec = fx.record || {};
  const live = liveFixtures(fx);
  const liveSet = new Set(live.map(m => m.home.team + '|' + m.away.team));
  const up = (fx.upcoming || []).filter(m => !liveSet.has(m.home.team + '|' + m.away.team))
              .find(m => m.kickoff) || (fx.upcoming || [])[0];
  const last = (fx.completed || [])[0];
  const ko = up && up.kickoff ? `<span class="pulse-cd" data-ko="${esc(up.kickoff)}">--:--:--</span>` : '';
  const lastHTML = last
    ? `${flagHTML(last.home.flag, 'flag-xs', last.home.team)}<b>${last.home_score}–${last.away_score}</b>${flagHTML(last.away.flag, 'flag-xs', last.away.team)} ${last.called ? '<span class="ok">✓</span>' : '<span class="miss">✗</span>'}`
    : 'the cup begins 11 June';
  // Middle cell: LIVE while a match is underway, otherwise the next countdown.
  let midK, midV;
  if (live.length) {
    const lm = live[0], extra = live.length > 1 ? ` <span class="pulse-more">+${live.length - 1}</span>` : '';
    midK = 'LIVE';
    midV = `<span class="profile-link" data-team="${esc(lm.home.team)}">${flagHTML(lm.home.flag, 'flag-xs', lm.home.team)}${esc(lm.home.team)}</span> v <span class="profile-link" data-team="${esc(lm.away.team)}">${esc(lm.away.team)}${flagHTML(lm.away.flag, 'flag-xs', lm.away.team)}</span> <span class="pulse-min"><span class="livedot"></span><b data-live-start="${esc(lm.kickoff)}">${matchPhase(lm).minute}'</b></span>${extra}`;
  } else {
    midK = 'NEXT';
    midV = up
      ? `<span class="profile-link" data-team="${esc(up.home.team)}">${flagHTML(up.home.flag, 'flag-xs', up.home.team)}${esc(up.home.team)}</span> v <span class="profile-link" data-team="${esc(up.away.team)}">${esc(up.away.team)}${flagHTML(up.away.flag, 'flag-xs', up.away.team)}</span> ${ko}`
      : '—';
  }
  const recHTML = rec.played ? `called <b>${rec.called}/${rec.played}</b> · ${pct(rec.pct)}` : 'record opens at kick-off';
  $('#muralPulse').innerHTML =
    `<div class="pulse-cell"><span class="pulse-k">LAST</span><span class="pulse-v">${lastHTML}</span></div>` +
    `<div class="pulse-cell${live.length ? ' pulse-live' : ''}"><span class="pulse-k">${midK}</span><span class="pulse-v">${midV}</span></div>` +
    `<div class="pulse-cell"><span class="pulse-k">MODEL</span><span class="pulse-v">${recHTML}</span></div>`;
  syncLivePill();
}

function muralGroups(g) {
  if (!g || g.error) { $('#muralGroups').innerHTML = ''; return; }
  $('#muralGroups').innerHTML = '<div class="mural-h">48 → 32 · the groups</div>' +
    Object.keys(g).sort().map(k => {
      const teams = g[k].map(t => {
        const c = t.adv >= 60 ? 'var(--teal)' : t.adv >= 35 ? 'var(--gold)' : 'var(--red)';
        return `<div class="mg-row profile-link" data-team="${esc(t.team)}" title="${esc(t.team)} — ${t.adv}% to advance">
          ${flagHTML(t.flag, 'flag-xs', t.team)}<span class="mg-nm">${esc(t.team)}</span>
          <span class="mg-bar"><i style="width:${Math.max(3, t.adv)}%;background:${c}"></i></span></div>`;
      }).join('');
      return `<div class="mg-card"><div class="mg-h">${esc(k)}</div>${teams}</div>`;
    }).join('');
}

function buildRiverSVG(bracket) {
  if (!bracket || bracket.error || !bracket.r32) return '<p class="loading">bracket forming…</p>';
  const wc = t => (t.winner === t.a.team ? t.a : t.b);          // the advancing (chalk/real) side
  const R = bracket.rounds || {};
  // The two finalists are the SF winners. The wallchart advances the head-to-head
  // favourite each tie, which can crown the higher-Elo finalist even when the OTHER
  // finalist is the model's title favourite (wins the cup more often across the sims).
  // The altar beside this river ranks teams by exactly those title odds, so we crown
  // the funnel by the same yardstick — the finalist with the higher title probability
  // — keeping the mural internally consistent. Falls back to the bracket's own
  // champion until the final is formed.
  const finalists = (R.sf || []).map(wc).filter(c => c && c.team);
  const championCard = finalists.length === 2
    ? ((finalists[0].p_win ?? -1) >= (finalists[1].p_win ?? -1) ? finalists[0] : finalists[1])
    : (bracket.champion || {});
  const cols = [bracket.r32.map(wc), (R.r16 || []).map(wc), (R.qf || []).map(wc),
                (R.sf || []).map(wc), [championCard]];
  const champ = championCard && championCard.team;
  const W = 300, H = 540, padX = 18, ys = [40, 158, 268, 366, 452];
  const xOf = (i, n) => padX + ((i + 0.5) / n) * (W - 2 * padX);
  let currents = '', nodes = '';
  for (let c = 0; c < cols.length - 1; c++) {
    cols[c].forEach((card, i) => {
      const j = Math.floor(i / 2), B = cols[c + 1][j] || {};
      const x1 = xOf(i, cols[c].length), x2 = xOf(j, cols[c + 1].length);
      const y1 = ys[c], y2 = ys[c + 1], my = (y1 + y2) / 2;
      const lit = champ && card.team === champ && B.team === champ;
      currents += `<path d="M${x1.toFixed(1)},${y1} C${x1.toFixed(1)},${my} ${x2.toFixed(1)},${my} ${x2.toFixed(1)},${y2}" fill="none" stroke="${lit ? 'var(--accent)' : 'rgba(236,227,208,.13)'}" stroke-width="${lit ? 3 : 1.1}"${lit ? ' class="lit"' : ''}/>`;
    });
  }
  const labels = ['R32', 'R16', 'QF', 'SF', '★'];
  cols.forEach((col, c) => {
    col.forEach((card, i) => {
      const x = xOf(i, col.length), y = ys[c], champNode = c === cols.length - 1;
      const lit = champ && card.team === champ, r = champNode ? 13 : (c >= 2 ? 7 : 4.5);
      const fill = (champNode || lit) ? 'var(--accent)' : (card.confed_color || '#8a8374');
      nodes += `<g class="river-node profile-link${lit ? ' lit' : ''}" data-team="${esc(card.team || '')}" tabindex="0" role="button" aria-label="${esc(card.team || '')}">
        <circle cx="${x.toFixed(1)}" cy="${y}" r="${r}" fill="${fill}" stroke="var(--bg)" stroke-width="2"/>
        ${champNode ? `<text x="${x.toFixed(1)}" y="${y + 4.5}" text-anchor="middle" font-size="13">🏆</text>` : ''}
        <title>${esc(card.team || '')}${champNode ? ' — projected champion' : ''}</title></g>`;
    });
    nodes += `<text x="5" y="${ys[c] + 3}" font-size="9" fill="var(--ink-soft)" class="river-lbl">${labels[c]}</text>`;
  });
  const cn = esc(championCard.team || '');
  return `<div class="mural-h">32 → 1 · the river</div>
    <svg viewBox="0 0 ${W} ${H}" class="river-svg" role="img" aria-label="Knockout funnel to ${cn}">
      ${currents}${nodes}
      <text x="${W / 2}" y="${H - 34}" text-anchor="middle" class="river-champ">${cn}</text>
      <text x="${W / 2}" y="${H - 18}" text-anchor="middle" class="river-sub">PROJECTED CHAMPION · ${pct(championCard.p_win)}</text>
    </svg>`;
}

function muralAltar(rep) {
  const odds = (rep && rep.title_odds) || [];
  if (!odds.length) { $('#muralAltar').innerHTML = ''; return; }
  const champ = odds[0];
  const pip = (v, cls = '') => `<span class="pip ${cls}" style="height:${Math.max(3, (v || 0) * 22)}px" title="${pct(v)}"></span>`;
  // Champion block + ranked list. The block is rebuilt only when the crowned
  // nation actually changes; otherwise we tween its % so a re-sim nudge reads as
  // a live tick rather than a full repaint. The list always morphs by team key.
  const host = $('#muralAltar'); if (!host) return;
  const champBlock = host.querySelector('.altar-champ');
  if (!champBlock || champBlock.dataset.team !== champ.team) {
    host.innerHTML = `
      <div class="mural-h">the answer</div>
      <div class="altar-champ profile-link sticker foil" data-team="${esc(champ.team)}">
        <div class="altar-k">THE MODEL CROWNS</div>
        ${flagHTML(champ.flag, 'flag', champ.team)}
        <div class="altar-nm">${esc(champ.team)}</div>
        <div class="altar-win"><span data-num="${champ.p_win}" data-fmt="pct">${pct(champ.p_win)}</span></div>
        <div class="altar-sub">to lift the trophy</div>
      </div>
      <div class="altar-list"></div>`;
  } else {
    const w = champBlock.querySelector('.altar-win span');
    if (w) { const from = parseFloat(w.dataset.num); w.dataset.num = champ.p_win; tweenNum(w, from); flash(w); }
  }
  paint('#muralAltar .altar-list', odds.slice(0, 6).map((o, i) =>
    `<div class="altar-row profile-link" data-mk="${esc(o.team)}" data-team="${esc(o.team)}">
        <span class="ar-rank">${i + 1}</span>${flagHTML(o.flag, 'flag-xs', o.team)}
        <span class="ar-nm">${esc(o.team)}</span>
        <span class="road" title="QF · SF · Final · Win">${pip(o.p_quarter)}${pip(o.p_semi)}${pip(o.p_final, 'f')}${pip(o.p_win, 'w')}</span>
        <span class="ar-win" data-num="${o.p_win}" data-fmt="pct">${pct(o.p_win)}</span></div>`).join(''));
}

function muralIntel(news) {
  const items = ((news && news.news) || []).slice(0, 8);
  if (!items.length) { $('#muralIntel').innerHTML = ''; return; }
  $('#muralIntel').innerHTML = '<span class="marg-k">INTEL</span>' + items.map(n => {
    const fl = (n.flags || []).slice(0, 1).map(f => `<i class="tag ${esc(f)}">${esc(f)}</i>`).join('');
    return `<span class="marg-item">${fl} ${esc(n.title)}</span>`;
  }).join('<span class="marg-dot">•</span>');
}

function startMuralClock() { startLiveTicker(); }   // legacy alias

// One global per-second heartbeat for everything time-sensitive on the page:
//  · [data-ko]          — countdowns to the next kickoff (mural pulse)
//  · [data-live-start]  — elapsed minute of a match in play (mc cards, pulse)
//  · the topbar LIVE pill state
// It runs for the life of the page (this is a live dashboard) but does almost
// nothing when there's no live/imminent match on screen.
function startLiveTicker() {
  if (startLiveTicker._t) return;                  // single shared interval
  const p = n => String(n).padStart(2, '0');
  const tick = () => {
    const now = Date.now();
    document.querySelectorAll('.pulse-cd[data-ko]').forEach(el => {
      let s = Math.max(0, Math.floor((Date.parse(el.getAttribute('data-ko')) - now) / 1000));
      if (s <= 0) { el.textContent = 'KICK-OFF'; return; }
      const d = Math.floor(s / 86400); s %= 86400;
      const h = Math.floor(s / 3600); s %= 3600; const m = Math.floor(s / 60), ss = s % 60;
      el.textContent = (d ? `${d}d ` : '') + `${p(h)}:${p(m)}:${p(ss)}`;
    });
    document.querySelectorAll('[data-live-start]').forEach(el => {
      const mins = Math.floor((now - Date.parse(el.getAttribute('data-live-start'))) / 60000);
      el.textContent = (mins >= 0 ? Math.max(1, mins) : 0) + "'";
    });
    syncLivePill();
  };
  tick(); startLiveTicker._t = setInterval(tick, 1000);
}

// Reflect real live state in the topbar pill: idle = "LIVE" reload affordance,
// active = "● LIVE n" with the underway-match count. Cached so we only touch the
// DOM when the count changes.
function syncLivePill() {
  const pill = $('#livePill'); if (!pill) return;
  const n = STATE.fixtures ? liveFixtures(STATE.fixtures).length : 0;
  if (syncLivePill._n === n) return;
  syncLivePill._n = n;
  pill.classList.toggle('is-live', n > 0);
  pill.innerHTML = `<span class="dot"></span> LIVE${n > 0 ? ' · ' + n : ''}`;
  pill.title = n > 0
    ? `${n} match${n > 1 ? 'es' : ''} in play — click to pull the latest model output`
    : 'Reload the latest model output';
}

// =========================================================================
//  CANONICAL TEAM PROFILE  —  one detail view, opened from any nation anywhere
// =========================================================================
let _lastFocus = null;
// Canonical 2026 World Cup national-team profile. One condensed card, opened from
// any nation anywhere (mural, rankings, odds, groups, intel, bracket). On a fine
// pointer it previews on hover and pins on click; on touch / small screens it
// opens as a tap-driven bottom sheet. Everything it shows already lives in STATE
// (meta/report/rankings/fixtures/news), so the card builds synchronously and hover
// feels instant — and it never dumps content at the page foot again.
const _pf = { team: null, pinned: false, anchor: null, t: 0 };
const _pfSmall = () => matchMedia('(max-width: 560px)').matches;
const _pfFine  = () => matchMedia('(hover: hover) and (pointer: fine)').matches;

function profileBody(team) {
  const f = _field(team);
  const odds = ((STATE.report && STATE.report.title_odds) || []).find(o => o.team === team) || {};
  const rk = (STATE.rankings || []).find(r => r.team === team) || {};
  const next = ((STATE.fixtures && STATE.fixtures.upcoming) || []).find(m => m.home.team === team || m.away.team === team);
  const teamNews = (((STATE.news && STATE.news.news)) || []).filter(n => (n.teams || []).includes(team)).slice(0, 2);
  const accent = f.confed_color || 'var(--gold)';
  const pip = (v, cls = '') => `<span class="pip ${cls}" style="height:${Math.max(4, (v || 0) * 26)}px" title="${pct(v)}"></span>`;

  let nextHTML = '';
  if (next) {
    const home = next.home.team === team, opp = home ? next.away : next.home;
    const call = next.fav === 'draw' ? 'Draw' : ((next.fav === 'home') === home ? 'Win' : 'Loss');
    const ph = matchPhase(next), k = fmtKick(next.kickoff);
    const when = ph.phase === 'live'
      ? `<b class="pf-live"><span class="livedot"></span>LIVE</b>`
      : (k ? esc(k.day) : '');
    nextHTML = `<div class="pf-row pf-next"><span class="pf-k">NEXT</span>
      <span class="pf-next-opp">${home ? 'vs' : 'at'} ${flagHTML(opp.flag, 'flag-xs', opp.team)} <b>${esc(opp.team)}</b></span>
      <span class="pf-call call-${call.toLowerCase()}">${call}</span>
      <span class="pf-when">${when}</span></div>`;
  }
  const intelHTML = teamNews.length
    ? `<div class="pf-row pf-intel"><span class="pf-k">INTEL</span><div class="pf-clips">${teamNews.map(n =>
        `<div class="pf-clip">${(n.flags || []).slice(0, 1).map(x => `<i class="tag ${esc(x)}">${esc(x)}</i>`).join('')} ${esc(n.title)}</div>`).join('')}</div></div>`
    : '';

  return `
    <div class="pf-banner" style="--c:${accent}">
      ${flagHTML(f.flag, 'flag-lg', team)}
      <div class="pf-id">
        <h3 id="profileName">${esc(team)}</h3>
        <div class="pf-sub">${f.group ? 'Group ' + esc(f.group) : ''}${f.confed ? (f.group ? ' · ' : '') + esc(f.confed) : ''}</div>
      </div>
      <span class="pf-tag">WC ’26</span>
    </div>
    <div class="pf-headline">
      ${starHTML(f.stars)}
      <span class="pf-win">${pct(odds.p_win)}<small>to win</small></span>
    </div>
    <div class="pf-stats">
      <div class="pf-stat"><span>Elo</span><b>${f.elo != null ? Math.round(f.elo) : '—'}</b></div>
      <div class="pf-stat"><span>Rank</span><b>${rk.rank ? '#' + rk.rank : '—'}</b></div>
      <div class="pf-stat"><span>Attack</span><b>${rk.attack != null ? rk.attack : '—'}</b></div>
      <div class="pf-stat"><span>Defence</span><b>${rk.defence != null ? rk.defence : '—'}</b></div>
    </div>
    <div class="pf-row pf-odds"><span class="pf-k">TITLE&nbsp;RUN</span>
      <span class="road" title="QF · SF · Final · Win">${pip(odds.p_quarter)}${pip(odds.p_semi)}${pip(odds.p_final, 'f')}${pip(odds.p_win, 'w')}</span></div>
    ${nextHTML}
    ${intelHTML}`;
}

function showProfile(team, anchor, pinned) {
  if (!team) return;
  const card = $('#profileCard'), scrim = $('#profileScrim');
  if (!card) return;
  clearTimeout(_pf.t);
  if (pinned) _lastFocus = document.activeElement;
  _pf.team = team; _pf.anchor = anchor || null; _pf.pinned = !!pinned;
  $('#profileCardBody').innerHTML = profileBody(team);
  card.classList.toggle('pinned', !!pinned);
  card.hidden = false;
  const sheet = !!pinned && _pfSmall();          // dim + lock scroll only for the mobile sheet
  if (scrim) scrim.hidden = !sheet;
  document.body.classList.toggle('modal-open', sheet);
  positionProfile(anchor);
  if (sheet) { const c = $('#profileClose'); if (c) c.focus({ preventScroll: true }); }
}

function positionProfile(anchor) {
  const card = $('#profileCard');
  if (!card || card.hidden) return;
  if (_pfSmall()) { card.style.left = ''; card.style.top = ''; return; }   // CSS handles the sheet
  if (!anchor || !anchor.getBoundingClientRect) return;
  const r = anchor.getBoundingClientRect();
  const cw = card.offsetWidth || 300, ch = card.offsetHeight || 240, M = 10;
  const vw = window.innerWidth, vh = window.innerHeight;
  let left = r.left, top = r.bottom + 8;
  if (left + cw > vw - M) left = vw - M - cw;
  if (left < M) left = M;
  if (top + ch > vh - M) top = Math.max(M, r.top - 8 - ch);              // flip above the anchor
  if (top < M) top = M;
  card.style.left = left + 'px'; card.style.top = top + 'px';
}

function hideProfile(force) {
  if (_pf.pinned && !force) return;
  clearTimeout(_pf.t);
  _pf.pinned = false; _pf.team = null; _pf.anchor = null;
  const card = $('#profileCard'), scrim = $('#profileScrim');
  if (card) card.hidden = true;
  if (scrim) scrim.hidden = true;
  document.body.classList.remove('modal-open');
}

function closeProfile() {
  hideProfile(true);
  if (_lastFocus && _lastFocus.focus) _lastFocus.focus();
}

// =========================================================================
//  LIVE AUTO-REFRESH  —  the heartbeat behind live match states + smooth updates
//  Re-pulls the volatile feeds in the background and lets the render functions
//  morph the changed numbers in place (no full-page reload, no scroll jump). The
//  cadence adapts: brisk while a match is live or about to start, relaxed
//  otherwise. Pauses while the tab is hidden and catches up on return.
// =========================================================================
async function refreshFeeds() {
  const get = (k, url, fb) => API(url).then(r => (STATE[k] = r)).catch(() => (STATE[k] ?? fb));
  const [report, fixtures, groupadv, bracket, news] = await Promise.all([
    get('report', '/api/report.json', {}), get('fixtures', '/api/fixtures.json', {}),
    get('groupadv', '/api/groupadv.json', {}), get('bracket', '/api/bracket.json', {}),
    get('news', '/api/news.json', {}),
  ]);
  return { report, fixtures, groupadv, bracket, news };
}
async function softRefresh(announce) {
  let d; try { d = await refreshFeeds(); } catch (e) { return; }
  renderOdds(d.report);
  renderFixtures(d.fixtures);
  renderGroups(d.groupadv);
  renderBracket(d.bracket);
  // don't stomp an active Intel filter — only repaint the clippings when showing all
  if (!$('#intelTeam')?.value) renderNews(d.news);
  // update the mural in place (no _WHOLE teardown → no flash, scroll preserved)
  muralPulse(d.fixtures); muralGroups(d.groupadv);
  const river = $('#muralRiver'); if (river) river.innerHTML = buildRiverSVG(d.bracket);
  muralAltar(d.report); muralIntel(d.news);
  const l = $('#muralLoading'); if (l) l.hidden = true;
  // keep the shared cache (used by team profiles) pointing at the fresh feeds
  _WHOLE = Promise.resolve({ report: STATE.report, groupadv: STATE.groupadv,
    bracket: STATE.bracket, fixtures: STATE.fixtures, news: STATE.news, media: STATE.media || {} });
  if (announce) toast('album refreshed ⚽');
}
function nextRefreshDelay() {
  const fx = STATE.fixtures;
  if (fx) {
    if (liveFixtures(fx).length) return 45000;                       // 45s while a match is live
    const soon = (fx.upcoming || []).some(m => {
      const ph = matchPhase(m); return ph.phase === 'soon' && ph.ms < 15 * 60000;
    });
    if (soon) return 60000;                                          // 1 min near a kickoff
  }
  return 300000;                                                     // 5 min otherwise
}
function scheduleRefresh() {
  clearTimeout(scheduleRefresh._t);
  scheduleRefresh._t = setTimeout(async () => {
    if (!document.hidden) await softRefresh(false);
    scheduleRefresh();
  }, nextRefreshDelay());
}

async function boot() {
  applyDailyTheme();
  scrollspy();
  initScrollProgress();
  skeletonFill();
  initReveal();

  // CSP-safe flag fallback: <img> error events don't bubble, so catch them in
  // the capture phase and swap a broken flag for its data-fb text fallback
  // (replaces the old inline onerror, which a strict script-src would block).
  document.addEventListener('error', e => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement) || !img.hasAttribute('data-fb')) return;
    const span = document.createElement('span');
    span.className = img.className + ' noflag';
    span.textContent = img.getAttribute('data-fb') || '';
    img.replaceWith(span);
  }, true);

  // meta first (drives pickers/cover), then everything else in parallel.
  // Every snapshot endpoint is fetched as `/api/<name>.json`: the live server
  // aliases these, and the static CDN build serves them as real files — so one
  // set of URLs works in both modes with no host-specific redirect rules.
  try {
    const meta = await API('/api/meta.json');
    if (meta.error) toast('engine: ' + meta.error);
    renderMeta(meta); renderMethod(meta);
  } catch (e) { toast('could not reach the engine — is the server running?'); }

  // static, always-available chrome
  wireSupport();
  renderKickoff(STATE.meta?.kickoff);
  startClock();
  $('#coverPromo')?.addEventListener('click', () => {
    document.getElementById('tactics')?.scrollIntoView({ block: 'start' });
    if (location.hash !== '#tactics') history.replaceState(null, '', '#tactics');
  });
  $('#shareBtn')?.addEventListener('click', doShare);

  const safe = (fn, p, target) => API(p).then(fn).catch(() => {
    if (target) $(target).innerHTML = '<p class="loading">unavailable — is PostgreSQL up?</p>';
  });
  safe(renderOdds, '/api/report.json', '#oddsList');
  safe(renderFixtures, '/api/fixtures.json', '#mcList');
  safe(renderBracket, '/api/bracket.json', '#bracket');
  safe(renderGroups, '/api/groupadv.json', '#groupsGrid');
  safe(renderRankings, '/api/rankings.json', '#rankBoard');
  safe(renderNews, '/api/news.json', '#clippings');
  renderWhole();                                   // page 01 — the mural funnel (self-fetches + caches)

  // Open the canonical team profile from any nation marked .profile-link[data-team]
  // (mural nodes, odds rows, group rows, pulse). Delegated so it survives re-renders.
  // rank-cards carry data-team too but NOT .profile-link, so their expand stays intact.
  // Profile card wiring: hover-to-preview (fine pointers only) + click/tap-to-pin.
  // Delegated so it survives every re-render. Rank-cards carry data-team but NOT
  // .profile-link, so their expand-trajectory behaviour stays intact.
  const linkOf = el => el && el.closest && el.closest('.profile-link[data-team]');
  document.addEventListener('click', e => {
    if (e.target.closest && e.target.closest('#profileCard')) return;          // clicks inside the card
    const link = linkOf(e.target);
    if (link) showProfile(link.getAttribute('data-team'), link, true);         // pin on click / tap
    else if (_pf.pinned) closeProfile();                                       // click-away dismisses
  });
  document.addEventListener('keydown', e => {
    const link = linkOf(e.target);
    if ((e.key === 'Enter' || e.key === ' ') && link) { e.preventDefault(); showProfile(link.getAttribute('data-team'), link, true); }
    if (e.key === 'Escape') closeProfile();
  });
  $('#profileClose').addEventListener('click', closeProfile);
  $('#profileScrim').addEventListener('click', closeProfile);

  if (_pfFine()) {                                   // hover preview never runs on touch
    document.addEventListener('mouseover', e => {
      if (_pf.pinned) return;
      const link = linkOf(e.target);
      if (!link || (e.target.closest && e.target.closest('#profileCard'))) return;
      clearTimeout(_pf.t);
      const team = link.getAttribute('data-team');
      _pf.t = setTimeout(() => { if (!_pf.pinned) showProfile(team, link, false); }, 120);
    });
    document.addEventListener('mouseout', e => {
      if (_pf.pinned) return;
      const to = e.relatedTarget;
      if (to && to.closest && (to.closest('#profileCard') || to.closest('.profile-link[data-team]'))) return;
      clearTimeout(_pf.t);
      _pf.t = setTimeout(() => hideProfile(false), 200);
    });
    const card = $('#profileCard');
    card.addEventListener('mouseenter', () => clearTimeout(_pf.t));
    card.addEventListener('mouseleave', () => { if (!_pf.pinned) { clearTimeout(_pf.t); _pf.t = setTimeout(() => hideProfile(false), 200); } });
  }
  window.addEventListener('scroll', () => {
    if (!_pf.team) return;
    if (_pf.pinned && !_pfSmall()) positionProfile(_pf.anchor);
    else if (!_pf.pinned) hideProfile(false);
  }, { passive: true });
  window.addEventListener('resize', () => { if (_pf.team) positionProfile(_pf.anchor); });

  // Page 09 is now "Collapse" — the run game, owned by the collapse.js ES module
  // (loaded separately). The legacy Quantum Tactics Lab renderers further down are
  // left in place but intentionally no longer wired here.

  // Match Centre tab switching
  $$('.mc-tab').forEach(b => b.addEventListener('click', () => {
    STATE.mcTab = b.dataset.mc; paintFixtures();
  }));

  // match lab wiring
  ['#pickHome', '#pickAway', '#neutralChk'].forEach(s => $(s).addEventListener('change', runPredict));
  $('#swapBtn').addEventListener('click', () => {
    const h = $('#pickHome').value; $('#pickHome').value = $('#pickAway').value; $('#pickAway').value = h; runPredict();
  });
  // Lazy: on the static build the Lab needs the ~1.2 MB offline prediction
  // matrix — don't make every visitor download it at boot. Arm the first
  // prediction when the Lab approaches the viewport (inputs above still fire it
  // immediately if the visitor gets there first).
  const lab = document.getElementById('lab');
  if (lab && 'IntersectionObserver' in window) {
    const labObs = new IntersectionObserver((es, o) => {
      if (es.some(e => e.isIntersecting)) { o.disconnect(); runPredict(); }
    }, { rootMargin: '600px 0px' });
    labObs.observe(lab);
  } else {
    runPredict();
  }

  // intel filter — live query, or client-side filter of the frozen feed when static
  $('#intelTeam').addEventListener('change', e => {
    const t = e.target.value;
    if (STATE.static) {
      const all = STATE.newsAll || [];
      renderNews({ news: t ? all.filter(n => (n.teams || []).includes(t)) : all, team: t });
    } else {
      safe(renderNews, `/api/news?n=30${t ? '&team=' + encodeURIComponent(t) : ''}`, '#clippings');
    }
  });

  // manual refresh — same smooth in-place path as the auto-poll, plus the
  // rankings + meta which don't ride the live loop. Re-arms the adaptive timer.
  $('#livePill').addEventListener('click', async () => {
    toast('pulling the latest model output…');
    await softRefresh(false);
    safe(renderRankings, '/api/rankings.json');
    const meta = await API('/api/meta.json').catch(() => null);
    if (meta) { renderMeta(meta); renderMethod(meta); }
    scheduleRefresh();
    setTimeout(() => toast('album refreshed ⚽'), 500);
  });

  // start the per-second clock for live minutes / countdowns + the adaptive
  // background refresh, and catch up immediately whenever the tab regains focus.
  startLiveTicker();
  scheduleRefresh();
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) { softRefresh(false); scheduleRefresh(); }
  });

  // ?solo=<section> renders just one page (used for single-section captures /
  // shareable crops); otherwise honour a #hash deep-link once content exists.
  const solo = new URLSearchParams(location.search).get('solo');
  if (solo) {
    $$('main > section').forEach(s => { if (s.id !== solo) s.style.display = 'none'; });
    const t = document.getElementById(solo);
    if (t) { t.style.paddingTop = '78px'; }
    window.scrollTo(0, 0);
  } else if (location.hash && location.hash.length > 1) {
    [120, 650, 1500].forEach(ms => setTimeout(() => {
      try { document.querySelector(location.hash)?.scrollIntoView({ block: 'start' }); }
      catch (e) { /* invalid selector — ignore */ }
    }, ms));
  }
}

document.addEventListener('DOMContentLoaded', boot);
