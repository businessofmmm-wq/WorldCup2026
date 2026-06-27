/*
 * POST /api/run/submit — verify a daily-challenge run and record it on the board.
 *
 * The cheat-resistance: we REPLAY the submitted (seed + per-match operator choices)
 * through the very same deterministic collapse-core.js the browser ran, against the
 * day's FROZEN snapshot (api/daily.json), and only accept the run if the recomputed
 * round + margin match the claim. A faked score fails the replay. Turnstile blocks
 * bot spam. Best run per handle per day is kept.
 */
import { resolveRun, ROUND_LABEL } from '../../../viz/static/collapse-core.js';

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store' } });

async function verifyTurnstile(secret, token, ip) {
  if (!secret) return true;                 // not configured yet → allow (pre-launch)
  if (!token) return false;
  const form = new FormData();
  form.append('secret', secret);
  form.append('response', token);
  if (ip) form.append('remoteip', ip);
  const r = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', { method: 'POST', body: form });
  const out = await r.json().catch(() => ({}));
  return !!out.success;
}

// Leaderboard score: how far you got dominates; weaker sides earn a difficulty
// bonus (a deep run with a minnow outranks the same round with a giant); margin
// breaks ties. All computed server-side from the frozen snapshot — unspoofable.
const difficulty = elo => Math.round(Math.max(0, Math.min(40, (2050 - elo) / 12)));
const leaderScore = (roundScore, margin, elo, champion) =>
  roundScore * 1000 + difficulty(elo) * 10 + Math.max(0, Math.min(90, margin + 30)) + (champion ? 5 : 0);

// A real run decides at most 8 player matches (3 group + 5 KO) choosing from 5
// operator ids — anything bigger is hostile input, rejected before it can burn
// CPU in the replay.
const opsValid = ops =>
  Array.isArray(ops) && ops.length <= 12 &&
  ops.every(o => Array.isArray(o) && o.length <= 8 &&
    o.every(id => typeof id === 'string' && id.length <= 24));

// Daily-rotating pseudonymous network key — raw IPs never touch the DB.
async function ipHash(day, ip) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${day}|${ip}`));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
}

const MAX_HANDLES_PER_IP_DAY = 8;

export async function onRequestPost({ request, env }) {
  let body;
  try { body = await request.json(); } catch { return json({ error: 'bad json' }, 400); }
  const { day, handle, team, seed, ops, claimedRound, claimedMargin, turnstileToken } = body || {};
  if (typeof day !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(day)) return json({ error: 'bad day' }, 400);
  if (!team || typeof team !== 'string' || team.length > 40) return json({ error: 'missing fields' }, 400);
  if (typeof seed !== 'number' || !Number.isInteger(seed) || seed < 0 || seed > 0xffffffff) return json({ error: 'bad seed' }, 400);
  if (!opsValid(ops)) return json({ error: 'bad ops' }, 400);
  const tag = String(handle || '')
    .replace(/[\u0000-\u001f\u007f\u200b-\u200f\u2028-\u202e]/g, '')
    .replace(/\s+/g, ' ').trim().slice(0, 18);
  if (!tag) return json({ error: 'handle required' }, 400);

  const ip = request.headers.get('CF-Connecting-IP') || '';
  if (!(await verifyTurnstile(env.TURNSTILE_SECRET, turnstileToken, ip))) return json({ error: 'turnstile failed' }, 403);

  // The day's frozen challenge (same snapshot the player used).
  const daily = await fetch(new URL('/api/daily.json', request.url)).then(r => r.json()).catch(() => null);
  if (!daily || !daily.snapshot) return json({ error: 'daily challenge unavailable' }, 503);
  if (daily.date !== day) return json({ error: 'stale challenge — reload for today' }, 409);
  if (daily.seed !== seed) return json({ error: 'seed mismatch' }, 400);
  if (!daily.snapshot.eg[team]) return json({ error: 'unknown team' }, 400);

  // REPLAY — the verifier. Same code, same seed, same ops ⇒ same outcome or it's a fake.
  let res;
  try { res = resolveRun(seed, team, ops, daily.snapshot); } catch { return json({ error: 'replay failed' }, 400); }
  if (res.roundReached !== claimedRound || res.margin !== claimedMargin)
    return json({ error: 'verification mismatch', got: { round: res.roundReached, margin: res.margin } }, 400);

  const elo = daily.snapshot.teams[team].elo;
  const score = leaderScore(res.roundScore, res.margin, elo, res.champion);

  if (!env.DB) return json({ ok: true, verified: true, score, roundLabel: ROUND_LABEL[res.roundReached], note: 'no DB binding — not persisted' });

  // Per-network cap: one IP may put at most MAX_HANDLES_PER_IP_DAY distinct
  // handles on a day's board (improving a handle it already owns is always
  // allowed). Blocks one valid run being replayed under endless fake names.
  const iph = await ipHash(day, ip);
  const exists = await env.DB.prepare(`SELECT 1 AS x FROM runs WHERE day=?1 AND handle=?2`)
    .bind(day, tag).first();
  if (!exists) {
    const cnt = await env.DB.prepare(`SELECT COUNT(*) AS n FROM runs WHERE day=?1 AND ip_hash=?2`)
      .bind(day, iph).first();
    if ((cnt?.n || 0) >= MAX_HANDLES_PER_IP_DAY)
      return json({ error: 'daily limit for this network reached — back tomorrow' }, 429);
  }

  await env.DB.prepare(
    `INSERT INTO runs (day, handle, team, round_reached, round_score, margin, seed, champion, elo, score, ip_hash)
     VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)
     ON CONFLICT(day, handle) DO UPDATE SET
       team=excluded.team, round_reached=excluded.round_reached, round_score=excluded.round_score,
       margin=excluded.margin, seed=excluded.seed, champion=excluded.champion, elo=excluded.elo,
       score=excluded.score, ip_hash=excluded.ip_hash, created_at=datetime('now')
     WHERE excluded.score > runs.score`
  ).bind(day, tag, team, res.roundReached, res.roundScore, res.margin, seed, res.champion ? 1 : 0, Math.round(elo), score, iph).run();

  const best = await env.DB.prepare(`SELECT score FROM runs WHERE day=?1 AND handle=?2`).bind(day, tag).first();
  const bestScore = best ? best.score : score;
  const ahead = await env.DB.prepare(`SELECT COUNT(*) AS n FROM runs WHERE day=?1 AND score > ?2`).bind(day, bestScore).first();
  const total = await env.DB.prepare(`SELECT COUNT(*) AS n FROM runs WHERE day=?1`).bind(day).first();
  return json({ ok: true, verified: true, rank: (ahead?.n || 0) + 1, total: total?.n || 1, score: bestScore, roundLabel: ROUND_LABEL[res.roundReached] });
}
