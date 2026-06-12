/*
 * GET /api/leaderboard?day=YYYY-MM-DD&limit=50 — today's verified daily board,
 * ranked by the server-computed score (round reached, difficulty bonus, margin).
 */
const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json', 'cache-control': 'public, max-age=20' } });

export async function onRequestGet({ request, env }) {
  const url = new URL(request.url);
  const day = url.searchParams.get('day');
  const limit = Math.min(100, Math.max(1, parseInt(url.searchParams.get('limit') || '50', 10)));
  if (!day) return json({ error: 'day required' }, 400);
  if (!env.DB) return json({ day, rows: [] });
  const { results } = await env.DB.prepare(
    `SELECT handle, team, round_reached, round_score, margin, champion, score
     FROM runs WHERE day=?1 ORDER BY score DESC, created_at ASC LIMIT ?2`
  ).bind(day, limit).all();
  return json({ day, rows: results || [] });
}
