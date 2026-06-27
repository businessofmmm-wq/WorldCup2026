/*
 * collapse-core.js — the deterministic engine for the WCPA "Collapse" run game.
 *
 * ONE module, run in three places (zero logic drift):
 *   • the browser, to play a run interactively (viz/static/collapse.js)
 *   • a Cloudflare Pages Function, to REPLAY a submitted run and verify the score
 *   • Node, for the headless determinism tests
 *
 * The game is its own deterministic simulator. It samples scorelines from the SAME
 * bivariate-Poisson grids the engine uses (rebuilt client-side from the exported
 * expected-goals means + the shared covariance lambda3 — see models/collapse_export.py;
 * base-grid parity with models/bivpoisson.scoreline_grid is exact to ~1e-7), but the
 * randomness is a single seeded mulberry32 stream, NOT Python's RNG. So the only
 * determinism contract is: identical (seed, team, ops) -> identical outcome, which
 * holds because every consumer runs this exact code.
 *
 * "Quantum tactics" are honest parameter transforms: each operator maps the player's
 * (for, against, lambda3) goal rates to new ones, shown to the player as before/after
 * odds. No fabricated football tactics, no club IP — the quantum naming is the literal
 * description of tilting the scoreline distribution.
 *
 * The run is driven by the runGen() generator, which yields a 'decide' step at each
 * player match (the UI supplies chosen operator ids) then a 'collapse' step (the UI
 * animates the sampled scoreline), and returns an 'end' summary. resolveRun() drives
 * the same generator from a recorded ops array — that is the verifier.
 */

// --------------------------------------------------------------------------- //
// Seeded PRNG — mulberry32 (uint32 seed -> float in [0,1))
// --------------------------------------------------------------------------- //
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// --------------------------------------------------------------------------- //
// Bivariate-Poisson scoreline grid (port of models/bivpoisson._bp_pmf, capped at
// max_goals so exact small factorials/combinations suffice — no lgamma needed).
// --------------------------------------------------------------------------- //
function fact(n) { let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; }
function comb(n, k) { return fact(n) / (fact(k) * fact(n - k)); }

function bpPmf(x, y, l1, l2, l3) {
  l1 = Math.max(l1, 1e-9); l2 = Math.max(l2, 1e-9);
  let s = 1.0;
  if (l3 > 0) {
    const ratio = l3 / (l1 * l2);
    s = 0.0;
    const mn = Math.min(x, y);
    for (let k = 0; k <= mn; k++) s += comb(x, k) * comb(y, k) * fact(k) * Math.pow(ratio, k);
  }
  return Math.exp(-(l1 + l2 + l3)) * (Math.pow(l1, x) / fact(x)) * (Math.pow(l2, y) / fact(y)) * s;
}

/** Grid from raw lambdas (l1=home-only, l2=away-only, l3=shared), row=home goals. */
export function bpGridFromLambdas(l1, l2, l3, maxGoals = 8) {
  const grid = []; let tot = 0;
  for (let i = 0; i <= maxGoals; i++) {
    const row = [];
    for (let j = 0; j <= maxGoals; j++) { const p = bpPmf(i, j, l1, l2, l3); row.push(p); tot += p; }
    grid.push(row);
  }
  if (tot > 0) for (let i = 0; i <= maxGoals; i++) for (let j = 0; j <= maxGoals; j++) grid[i][j] /= tot;
  return grid;
}

/** Grid from expected-goals means + global lambda3 — carves l3 exactly as the engine. */
export function bpGrid(meanH, meanA, lambda3, maxGoals = 8) {
  let l3 = Math.min(lambda3, meanH - 1e-6, meanA - 1e-6);
  if (l3 < 0) l3 = 0;
  return bpGridFromLambdas(meanH - l3, meanA - l3, l3, maxGoals);
}

/** 1X2 collapse probabilities (home win / draw / away win) from a grid. */
export function oddsFromGrid(grid) {
  let pHome = 0, pDraw = 0, pAway = 0;
  for (let i = 0; i < grid.length; i++) for (let j = 0; j < grid.length; j++) {
    const p = grid[i][j];
    if (i > j) pHome += p; else if (i < j) pAway += p; else pDraw += p;
  }
  return { pHome, pDraw, pAway };
}

/** Sample one [homeGoals, awayGoals] via inverse-CDF (port of _sample_score). */
export function sampleScore(grid, rng) {
  const r = rng(); let cum = 0; const n = grid.length;
  for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) { cum += grid[i][j]; if (r <= cum) return [i, j]; }
  return [n - 1, n - 1];
}

// --------------------------------------------------------------------------- //
// Quantum operators — transforms on the player's (F=for, A=against, L3=shared).
// Magnitudes live here; tune freely. ctx = { oppA, myElo, oppElo }.
// --------------------------------------------------------------------------- //
function clamp(x, lo, hi) { return Math.max(lo, Math.min(hi, x)); }

export const OPERATORS = [
  {
    id: 'coherence', name: 'Coherence', cost: 1, glyph: '⟩',
    quantum: 'Constructive interference toward the goal-state',
    desc: 'Sharpen the attack — more scoring, a sliver more open at the back.',
    apply: (F, A, L3) => [F * 1.18, A * 0.98, L3],
  },
  {
    id: 'press', name: 'Superposition Press', cost: 2, glyph: '⇋',
    quantum: 'Hold many states at once',
    desc: 'Throw the game open both ways — thrash or be thrashed.',
    apply: (F, A, L3) => [F * 1.16, A * 1.16, L3 * 0.5],
  },
  {
    id: 'wall', name: "Observer's Wall", cost: 2, glyph: '▢',
    quantum: 'Measurement collapses the chaos',
    desc: 'Freeze the match — fewer goals against, more draws.',
    apply: (F, A, L3) => [F * 0.95, A * 0.74, L3 + 0.18],
  },
  {
    id: 'entangle', name: 'Entanglement', cost: 2, glyph: '∞',
    quantum: "Your output couples to the opponent's",
    desc: 'Counter-attack — the more they threaten, the more you break.',
    apply: (F, A, L3, ctx) => [F + 0.45 * ctx.oppA, A * 1.06, L3],
  },
  {
    id: 'tunnel', name: 'Tunneling', cost: 3, glyph: '⤳',
    quantum: 'Pass through a barrier you should not',
    desc: 'Underdog spike — the bigger the gap, the bigger the surge.',
    apply: (F, A, L3, ctx) => {
      const gap = clamp((ctx.oppElo - ctx.myElo) / 400, 0, 1.2);
      return [F * (1.25 + 0.5 * gap), A * 0.98, Math.max(0, L3 - 0.05)];
    },
  },
];
const OP_BY_ID = Object.fromEntries(OPERATORS.map(o => [o.id, o]));

/** Quanta budget per round and the (non-chosen) decoherence noise that rises each round. */
export const BUDGET = { group: 3, r32: 3, r16: 4, qf: 4, sf: 5, final: 5 };
const DECO_INDEX = { group: 0, r32: 1, r16: 2, qf: 3, sf: 4, final: 5 };
export const ROUND_SCORE = { group: 0, r32: 1, r16: 2, qf: 3, sf: 4, final: 5, champion: 6 };
export const ROUND_LABEL = {
  group: 'Group stage', r32: 'Round of 32', r16: 'Round of 16',
  qf: 'Quarter-final', sf: 'Semi-final', final: 'Final', champion: 'Champion',
};

export function decoherence(roundName) { return 0.05 * (DECO_INDEX[roundName] || 0); }

/** Keep operators greedily until the quanta budget is spent (drops over-budget/dupes). */
export function sanitizeChoice(choice, budget) {
  const seen = new Set(); const out = []; let spent = 0;
  for (const id of (choice || [])) {
    const op = OP_BY_ID[id];
    if (!op || seen.has(id)) continue;
    if (spent + op.cost > budget) continue;
    seen.add(id); out.push(id); spent += op.cost;
  }
  return out;
}

// --------------------------------------------------------------------------- //
// Match context -> operator-modified grid (used identically for the UI preview
// and the generator's resolution, so what the player sees is what they get).
// --------------------------------------------------------------------------- //
export function playerGridForCtx(ctx, choice, data) {
  const { homeTeam, awayTeam, playerIsHome, playerTeam, opp, roundName } = ctx;
  const [mh, ma] = data.eg[homeTeam][awayTeam];
  let l3 = Math.min(data.lambda3, mh - 1e-6, ma - 1e-6); if (l3 < 0) l3 = 0;
  const l1 = mh - l3, l2 = ma - l3;
  let F = playerIsHome ? l1 : l2;      // player's scoring rate
  let A = playerIsHome ? l2 : l1;      // player's conceding rate
  const oppA0 = A;
  const cx = { oppA: oppA0, myElo: data.teams[playerTeam].elo, oppElo: data.teams[opp].elo };
  for (const id of sanitizeChoice(choice, ctx.budget)) [F, A, l3] = OP_BY_ID[id].apply(F, A, l3, cx);
  const d = decoherence(roundName);    // fatigue: rising variance deep in the run
  F *= (1 + d); A *= (1 + d);
  F = Math.max(F, 1e-6); A = Math.max(A, 1e-6);
  l3 = Math.max(0, Math.min(l3, F - 1e-6, A - 1e-6));
  const nl1 = playerIsHome ? F : A, nl2 = playerIsHome ? A : F;
  return bpGridFromLambdas(nl1, nl2, l3, data.max_goals || 8);
}

/** UI helper: grid + odds for a candidate operator selection (no RNG, <1ms). */
export function previewMatch(ctx, choice, data) {
  const grid = playerGridForCtx(ctx, choice, data);
  return { grid, odds: oddsFromGrid(grid) };
}

// --------------------------------------------------------------------------- //
// Field helpers (auto matches between non-player teams)
// --------------------------------------------------------------------------- //
function fieldGridFactory(data) {
  const cache = new Map();
  return function (a, b) {
    const key = a + '|' + b;
    let g = cache.get(key);
    if (!g) { const [mh, ma] = data.eg[a][b]; g = bpGrid(mh, ma, data.lambda3, data.max_goals || 8); cache.set(key, g); }
    return g;
  };
}

function compareKeyDesc(x, y) { for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return y[i] - x[i]; return 0; }

function shuffleInPlace(arr, rng) {
  for (let i = arr.length - 1; i > 0; i--) { const j = Math.floor(rng() * (i + 1)); [arr[i], arr[j]] = [arr[j], arr[i]]; }
  return arr;
}

const PAIRS = [[0, 1], [0, 2], [0, 3], [1, 2], [1, 3], [2, 3]];

function koRoundName(m) {
  m = +m;
  if (m >= 73 && m <= 88) return 'r32';
  if (m >= 89 && m <= 96) return 'r16';
  if (m >= 97 && m <= 100) return 'qf';
  if (m >= 101 && m <= 102) return 'sf';
  return 'final';
}

/** Map eight qualifying third-place groups onto the eight T-slots (Annex C backtrack). */
function assignThirds(thirdGroups, allowed, rng) {
  const avail = Object.keys(thirdGroups);
  const assign = {};
  function bt(remaining, used) {
    if (remaining.length === 0) return true;
    remaining = remaining.slice().sort((a, b) =>
      avail.filter(g => allowed[a].includes(g) && !used.has(g)).length -
      avail.filter(g => allowed[b].includes(g) && !used.has(g)).length);
    const s = remaining[0];
    const cands = shuffleInPlace(avail.filter(g => allowed[s].includes(g) && !used.has(g)), rng);
    for (const g of cands) {
      assign[s] = g;
      const nu = new Set(used); nu.add(g);
      if (bt(remaining.slice(1), nu)) return true;
      delete assign[s];
    }
    return false;
  }
  bt(Object.keys(allowed), new Set());
  const out = {};
  for (const s in assign) out[s] = thirdGroups[assign[s]];
  return out;
}

// --------------------------------------------------------------------------- //
// The run generator — yields 'decide' / 'collapse' steps, returns an 'end' summary.
// --------------------------------------------------------------------------- //
export function* runGen(seed, team, data) {
  if (!data.eg[team]) throw new Error('unknown team: ' + team);
  const rng = mulberry32((seed >>> 0) ^ 0x9e3779b9);
  const fieldGrid = fieldGridFactory(data);
  const br = data.bracket;
  const GROUPS = br.groups;
  const GROUP_ORDER = Object.keys(GROUPS).sort();
  const path = [];
  let margin = 0;

  const apply = (st, h, a, hs, as_) => {
    st[h].gf += hs; st[a].gf += as_;
    st[h].gd += hs - as_; st[a].gd += as_ - hs;
    if (hs > as_) st[h].pts += 3; else if (as_ > hs) st[a].pts += 3; else { st[h].pts += 1; st[a].pts += 1; }
  };

  // ---- GROUP STAGE -------------------------------------------------------- //
  const tables = {}, allStats = {};
  let myGroup = null;
  for (const g of GROUP_ORDER) {
    const t4 = GROUPS[g];
    if (t4.includes(team)) myGroup = g;
    const st = {}; for (const t of t4) st[t] = { pts: 0, gd: 0, gf: 0 };
    for (const [i, j] of PAIRS) {
      const h = t4[i], a = t4[j];
      let hs, as_;
      if (h === team || a === team) {
        const playerIsHome = (h === team), opp = playerIsHome ? a : h;
        const ctx = {
          phase: 'group', roundName: 'group', group: g, playerTeam: team, opp,
          oppMeta: data.teams[opp], playerIsHome, homeTeam: h, awayTeam: a, budget: BUDGET.group,
        };
        const base = previewMatch(ctx, [], data);
        const choice = yield { type: 'decide', ctx, base, decoherence: decoherence('group') };
        const grid = playerGridForCtx(ctx, choice, data);
        [hs, as_] = sampleScore(grid, rng);
        const myG = playerIsHome ? hs : as_, oppG = playerIsHome ? as_ : hs;
        margin += myG - oppG;
        const outcome = myG > oppG ? 'win' : myG < oppG ? 'loss' : 'draw';
        path.push({ stage: 'group', opp, score: [hs, as_], playerIsHome, outcome, ops: sanitizeChoice(choice, BUDGET.group) });
        yield { type: 'collapse', ctx, score: [hs, as_], grid, odds: oddsFromGrid(grid), outcome, advanced: null };
      } else {
        [hs, as_] = sampleScore(fieldGrid(h, a), rng);
      }
      apply(st, h, a, hs, as_);
    }
    const keyed = t4.map(t => ({ t, k: [st[t].pts, st[t].gd, st[t].gf, rng()] }));
    keyed.sort((x, y) => compareKeyDesc(x.k, y.k));
    tables[g] = keyed.map(o => o.t);
    Object.assign(allStats, st);
  }

  // best thirds + qualification
  const winByG = {}, runByG = {};
  for (const g of GROUP_ORDER) { winByG[g] = tables[g][0]; runByG[g] = tables[g][1]; }
  const thirds = GROUP_ORDER.map(g => {
    const t = tables[g][2], s = allStats[t];
    return { g, t, k: [s.pts, s.gd, s.gf, rng()] };
  });
  thirds.sort((x, y) => compareKeyDesc(x.k, y.k));
  const thirdGroups = {};
  for (const e of thirds.slice(0, 8)) thirdGroups[e.g] = e.t;

  const myRank = tables[myGroup].indexOf(team);
  const advanced = myRank < 2 || (myRank === 2 && thirdGroups[myGroup] === team);
  if (!advanced) {
    return endSummary('group', margin, path, false, { tables, myGroup, myRank });
  }

  // ---- KNOCKOUT ----------------------------------------------------------- //
  const slot = {};
  for (const g of GROUP_ORDER) { slot['1' + g] = winByG[g]; slot['2' + g] = runByG[g]; }
  const tAssign = assignThirds(thirdGroups, br.allowed_thirds, rng);
  for (const s in tAssign) slot[s] = tAssign[s];

  const R32 = {}; for (const [m, s1, s2] of br.r32) R32[m] = [s1, s2];
  const BR = br.bracket;                       // {"89":[74,77],...}
  const childToParent = {};
  for (const pm in BR) for (const c of BR[pm]) childToParent[c] = +pm;

  const memo = new Map();
  function winner(m) {                          // field-only subtree winner
    if (memo.has(m)) return memo.get(m);
    let a, b;
    if (R32[m]) { a = slot[R32[m][0]]; b = slot[R32[m][1]]; }
    else { const [f1, f2] = BR[String(m)]; a = winner(f1); b = winner(f2); }
    const grid = fieldGrid(a, b);
    let [hs, as_] = sampleScore(grid, rng);
    let w;
    if (hs > as_) w = a; else if (as_ > hs) w = b;
    else { const o = oddsFromGrid(grid); const pa = o.pHome / ((o.pHome + o.pAway) || 1); w = rng() < pa ? a : b; }
    memo.set(m, w); return w;
  }

  // locate the player's R32 tie
  let m, playerIsHome, opp;
  for (const [mm, s1, s2] of br.r32) {
    if (slot[s1] === team || slot[s2] === team) { m = mm; playerIsHome = (slot[s1] === team); opp = playerIsHome ? slot[s2] : slot[s1]; break; }
  }

  while (true) {
    const roundName = koRoundName(m);
    const homeTeam = playerIsHome ? team : opp, awayTeam = playerIsHome ? opp : team;
    const ctx = {
      phase: 'ko', roundName, m, playerTeam: team, opp, oppMeta: data.teams[opp],
      playerIsHome, homeTeam, awayTeam, budget: BUDGET[roundName],
    };
    const base = previewMatch(ctx, [], data);
    const choice = yield { type: 'decide', ctx, base, decoherence: decoherence(roundName) };
    const grid = playerGridForCtx(ctx, choice, data);
    const [hs, as_] = sampleScore(grid, rng);
    let won, viaShootout = false;
    if (hs === as_) {
      const o = oddsFromGrid(grid);
      const pHomeWin = o.pHome / ((o.pHome + o.pAway) || 1);
      won = rng() < (playerIsHome ? pHomeWin : 1 - pHomeWin); viaShootout = true;
    } else {
      const myG = playerIsHome ? hs : as_, oppG = playerIsHome ? as_ : hs;
      won = myG > oppG; margin += myG - oppG;
    }
    path.push({ stage: roundName, opp, score: [hs, as_], playerIsHome, outcome: won ? 'win' : 'loss', viaShootout, ops: sanitizeChoice(choice, BUDGET[roundName]) });
    yield { type: 'collapse', ctx, score: [hs, as_], grid, odds: oddsFromGrid(grid), outcome: won ? 'win' : 'loss', viaShootout, advanced: won };

    if (!won) return endSummary(roundName, margin, path, false, { tables, myGroup, myRank });
    if (m === 104) return endSummary('champion', margin, path, true, { tables, myGroup, myRank });

    const parent = childToParent[m];
    const [f1, f2] = BR[String(parent)];
    playerIsHome = (f1 === m);
    opp = winner(playerIsHome ? f2 : f1);
    m = parent;
  }
}

function endSummary(roundReached, margin, path, champion, extra) {
  return {
    type: 'end', roundReached, roundScore: ROUND_SCORE[roundReached],
    roundLabel: ROUND_LABEL[roundReached], margin, champion, path, ...extra,
  };
}

// --------------------------------------------------------------------------- //
// resolveRun — drive runGen from a recorded ops array. THIS is the verifier:
// the Pages Function calls it with the frozen daily snapshot to replay a claim.
// `ops` is the per-player-match list of operator-id arrays, in play order.
// --------------------------------------------------------------------------- //
export function resolveRun(seed, team, ops, data) {
  const g = runGen(seed, team, data);
  let r = g.next(); let i = 0;
  while (!r.done) r = (r.value.type === 'decide') ? g.next(ops[i++] || []) : g.next();
  return r.value;
}

// Convenience for non-module consumers (browser global / quick Node eval).
if (typeof globalThis !== 'undefined') {
  globalThis.CollapseCore = {
    mulberry32, bpGrid, bpGridFromLambdas, oddsFromGrid, sampleScore,
    OPERATORS, BUDGET, ROUND_SCORE, ROUND_LABEL, decoherence, sanitizeChoice,
    playerGridForCtx, previewMatch, runGen, resolveRun,
  };
}
