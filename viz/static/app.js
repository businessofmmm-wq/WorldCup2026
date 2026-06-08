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
  if (url) return `<img class="${cls}" src="${esc(url)}" alt="${esc(alt || '')}" data-fb="${fb}" loading="lazy" />`;
  return `<span class="${cls} noflag">${fb}</span>`;
}
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), 2200);
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
  $('#podium').innerHTML = odds.slice(0, 3).map((o, i) => `
    <div class="pod pod-${i + 1}">
      <div class="sticker foil tape">
        <div class="medal">${medals[i]}</div>
        ${flagHTML(o.flag, 'flag', o.team)}
        <div class="pod-team">${esc(o.team)}</div>
        <div class="pod-win">${pct(o.p_win)}</div>
        <div class="pod-sub">final ${pct(o.p_final)} · semi ${pct(o.p_semi)}</div>
      </div>
    </div>`).join('');

  // cover favourite sticker
  if (odds[0]) {
    $('#coverFav').innerHTML = `
      <div class="sticker foil tape" style="max-width:280px;padding:16px 18px;text-align:center">
        <div style="font-family:var(--font-lab);letter-spacing:2px;color:var(--terra)">MODEL FAVOURITE</div>
        ${flagHTML(odds[0].flag, 'flag', odds[0].team)}
        <div style="font-family:var(--font-disp);font-size:2rem;margin-top:8px">${esc(odds[0].team)}</div>
        <div style="font-family:var(--font-badge);font-size:1.6rem;color:var(--terra)">${pct(odds[0].p_win)}</div>
        <div class="muted" style="font-size:.8rem">to lift the trophy</div>
      </div>`;
  }

  // full ranked list
  $('#oddsList').innerHTML = odds.map((o, i) => {
    const w = Math.max(2, (o.p_win / maxWin) * 100);
    const pip = (v, cls = '') => `<span class="pip ${cls}" style="height:${Math.max(3, (v || 0) * 24)}px" title="${pct(v)}"></span>`;
    return `
      <div class="odds-row">
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
          <span class="owin">${pct(o.p_win)}</span>
        </div>
      </div>`;
  }).join('');
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
  $('#groupsGrid').innerHTML = Object.keys(g).sort().map((k, gi) => {
    const rows = g[k].map((t, i) => `
      <div class="grow">
        <span class="gpos">${i + 1}</span>
        ${flagHTML(t.flag, 'flag-sm', t.team)}
        <span class="gnm">${esc(t.team)}<small>Elo ${Math.round(t.elo)} · ${esc(t.confed)}</small></span>
        <div class="advwrap">
          <div class="advbar"><span style="width:${t.adv}%;background:${t.adv >= 60 ? 'var(--teal)' : t.adv >= 35 ? 'var(--gold)' : 'var(--red)'}"></span></div>
          <span class="advpct">${t.adv}%</span>
        </div>
      </div>`).join('');
    return `<div class="group-card" style="--rot:${rots[gi % rots.length]}deg">
      <div class="gc-head">
        <span class="gname">Group ${k}</span>
        ${k === death ? '<span class="gtag death">💀 Group of Death</span>'
                      : '<span class="gtag">Adv%</span>'}
      </div>${rows}</div>`;
  }).join('');
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
function mcCard(m, done) {
  const favHome = m.fav === 'home', favAway = m.fav === 'away';
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
    return `<div class="mc-card done">
        <div class="mc-date">${fmtDate(m.date)}</div>
        ${mcSide(m.home, 'home', favHome, winH ? true : winA ? false : null)}
        ${mid}
        ${mcSide(m.away, 'away', favAway, winA ? true : winH ? false : null)}
      </div>`;
  }
  mid = `<div class="mc-mid">
      ${wdwBar(m.p_home, m.p_draw, m.p_away, m.fav)}
      <div class="mc-line">xG ${m.exp_home_goals.toFixed(1)}–${m.exp_away_goals.toFixed(1)} · likely <b>${esc(m.top_scoreline)}</b>${m.neutral ? '' : ' · home adv'}</div>
    </div>`;
  return `<div class="mc-card">
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
  // default to results once any exist, else upcoming
  if (!STATE.mcTab) STATE.mcTab = (rec.played ? 'completed' : 'upcoming');
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
  const list = (tab === 'completed' ? data.completed : data.upcoming) || [];
  if (!list.length) {
    $('#mcList').innerHTML = `<p class="loading">${tab === 'completed'
      ? 'No results yet — the tournament hasn\'t kicked off. Check back from ' + fmtDate(data.kickoff) + '.'
      : 'No upcoming fixtures scheduled.'}</p>`;
    return;
  }
  // group by date with a day header
  let html = '', day = null;
  for (const m of list) {
    if (m.date !== day) { day = m.date; html += `<div class="mc-day">${fmtDate(m.date)}</div>`; }
    html += mcCard(m, tab === 'completed');
  }
  $('#mcList').innerHTML = html;
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
//  CLUB SHOP  (non-gambling affiliate shelf — #Ad)
// =========================================================================
// Edit these to your real affiliate links/IDs before launch (see LAUNCH.md).
// Honest placeholders for now: on-brand retro / blokecore football culture.
const SHOP = [
  { emoji: '👕', name: 'Retro & blokecore shirts', tag: 'Classic national-team & terrace kits', href: '#', note: 'affiliate' },
  { emoji: '🧣', name: 'Scarves & terrace wear', tag: 'Bar scarves and casual labels', href: '#', note: 'affiliate' },
  { emoji: '📒', name: 'Sticker albums & swaps', tag: 'The real thing — collect & trade', href: '#', note: 'affiliate' },
  { emoji: '⚽', name: 'Retro match balls', tag: 'Tango, Azteca, Etrusco reissues', href: '#', note: 'affiliate' },
];
function renderShop() {
  const el = $('#shopShelf'); if (!el) return;
  el.innerHTML = SHOP.map((s, i) => `
    <a class="shop-item" href="${esc(s.href)}" target="_blank" rel="noopener nofollow sponsored"
       style="--rot:${[-1.4, .9, -.7, 1.2][i % 4]}deg">
      <div class="shop-emoji">${s.emoji}</div>
      <div class="shop-name">${esc(s.name)}</div>
      <div class="shop-tag">${esc(s.tag)}</div>
      <div class="shop-cta">Shop →</div>
    </a>`).join('');
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
  ['odds', 'matches', 'wallchart', 'groups', 'rankings', 'lab', 'intel', 'method']
    .forEach(id => { const s = document.getElementById(id); if (s) obs.observe(s); });
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
//  BOOT
// =========================================================================
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
  renderShop();
  wireSupport();
  renderKickoff(STATE.meta?.kickoff);
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

  // Match Centre tab switching
  $$('.mc-tab').forEach(b => b.addEventListener('click', () => {
    STATE.mcTab = b.dataset.mc; paintFixtures();
  }));

  // match lab wiring
  ['#pickHome', '#pickAway', '#neutralChk'].forEach(s => $(s).addEventListener('change', runPredict));
  $('#swapBtn').addEventListener('click', () => {
    const h = $('#pickHome').value; $('#pickHome').value = $('#pickAway').value; $('#pickAway').value = h; runPredict();
  });
  runPredict();

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

  // live refresh
  $('#livePill').addEventListener('click', async () => {
    toast('pulling the latest model output…');
    safe(renderOdds, '/api/report.json'); safe(renderFixtures, '/api/fixtures.json');
    safe(renderBracket, '/api/bracket.json');
    safe(renderGroups, '/api/groupadv.json'); safe(renderRankings, '/api/rankings.json');
    safe(renderNews, '/api/news.json');
    const meta = await API('/api/meta.json').catch(() => null);
    if (meta) { renderMeta(meta); renderMethod(meta); }
    setTimeout(() => toast('album refreshed ⚽'), 600);
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
