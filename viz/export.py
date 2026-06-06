#!/usr/bin/env python
"""
Static-snapshot exporter for the WCPA (World Cup Prediction Album) dashboard.

The live dashboard (viz/server.py) reads Postgres + runs the ensemble on demand.
That can't go public safely (a DB and compute endpoints exposed to the world).
So we instead *snapshot* the whole thing to plain JSON + the static front-end and
deploy that to a free CDN (Cloudflare Pages / Netlify). The result has no server,
no database and no attack surface — it scales through a World-Cup traffic spike
for $0, and stays "live" by re-running this export on a schedule (see run loop).

    python run.py export                 # build ./dist
    python run.py export ../site         # build elsewhere

What it writes into <dist>/:
    index.html, about.html, app.js, style.css, favicon.svg   (copied verbatim)
    api/meta.json report.json groupadv.json rankings.json
        news.json bracket.json fixtures.json                 (endpoint snapshots)
    api/history.json            per-team Elo trajectories (rankings sparklines)
    api/predict_matrix.json     every 2-of-48 prediction (the Match Lab, offline)
    _redirects _headers robots.txt sitemap.xml               (CDN config)

The front-end (app.js) detects `meta.static === true` and serves the Match Lab,
the rankings trajectories and the intel filter from these files instead of a
live API — so the static build is fully interactive, just frozen at export time.
"""
from __future__ import annotations
import json
import os
import shutil
import sys
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config                                    # noqa: E402
import db                                         # noqa: E402
from models import field_2026                     # noqa: E402
from viz import server                            # noqa: E402

PROD_URL = "https://wcpa26.com"


def _write_json(path: str, obj) -> int:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))
    return os.path.getsize(path)


def _snapshot_endpoints(api_dir: str) -> None:
    """Freeze each read endpoint to <api>/<name>.json (query-less variants)."""
    jobs = {
        "meta": (server.ep_meta, {}),
        "report": (server.ep_report, {}),
        "groupadv": (server.ep_groupadv, {}),
        "rankings": (server.ep_rankings, {"n": ["60"]}),
        "news": (server.ep_news, {"n": ["40"]}),
        "bracket": (server.ep_bracket, {}),
        "fixtures": (server.ep_fixtures, {}),
    }
    for name, (fn, q) in jobs.items():
        data = fn(q)
        if name == "meta":               # flag the build as static for the client
            data["static"] = True
            data["base_url"] = PROD_URL
            data["exported"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        kb = _write_json(os.path.join(api_dir, f"{name}.json"), data) / 1024
        print(f"  api/{name}.json  ({kb:.0f} KB)")


def _export_history(api_dir: str) -> None:
    """One file of Elo trajectories, keyed by team — powers the rankings
    sparklines without a live /api/history endpoint."""
    teams = set(field_2026.FIELD)
    with db.connect() as conn:
        top = conn.execute(
            "SELECT team FROM team_ratings WHERE elo IS NOT NULL "
            "ORDER BY elo DESC LIMIT 60").fetchall()
        teams.update(t for (t,) in top)
        out = {}
        for team in teams:
            res = conn.execute(
                "SELECT match_date, elo FROM elo_history WHERE team=%s "
                "ORDER BY match_date", (team,)).fetchall()
            series = [(d.isoformat(), round(e, 1)) for d, e in res]
            if len(series) > 90:          # downsample, always keep the last point
                step = len(series) / 90
                idx = sorted({int(i * step) for i in range(90)} | {len(series) - 1})
                series = [series[i] for i in idx]
            if series:
                out[team] = series
    kb = _write_json(os.path.join(api_dir, "history.json"), out) / 1024
    print(f"  api/history.json  ({len(out)} teams, {kb:.0f} KB)")


def _export_predict_matrix(api_dir: str) -> None:
    """Precompute every two-of-48 ensemble prediction (both venues) so the live
    Match Lab works with no server. Keyed "home|away|n" (n=1 neutral, 0 home)."""
    p = server.predictor()
    field = sorted(field_2026.FIELD)
    matrix = {}
    pairs = 0
    for home in field:
        for away in field:
            if home == away:
                continue
            for neutral in (True, False):
                r = p.predict(home, away, neutral=neutral, log=False)
                grid, _, _ = p.goals.scoreline_grid(home, away, neutral=neutral)
                flat = sorted(((grid[i][j], i, j)
                               for i in range(len(grid)) for j in range(len(grid))),
                              reverse=True)[:6]
                matrix[f"{home}|{away}|{1 if neutral else 0}"] = {
                    "ph": round(r["p_home"], 4), "pd": round(r["p_draw"], 4),
                    "pa": round(r["p_away"], 4),
                    "xgh": round(r["exp_home_goals"], 3),
                    "xga": round(r["exp_away_goals"], 3),
                    "ts": r["top_scoreline"],
                    "tsl": [{"score": f"{i}-{j}", "p": round(pr, 4)} for pr, i, j in flat],
                    "eh": round(r["elo_home"], 1), "ea": round(r["elo_away"], 1),
                }
                pairs += 1
        print(f"    matrix … {home}", end="\r")
    kb = _write_json(os.path.join(api_dir, "predict_matrix.json"), matrix) / 1024
    print(f"  api/predict_matrix.json  ({pairs} predictions, {kb:.0f} KB)   ")


def _copy_static(dist: str) -> None:
    static = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    for name in os.listdir(static):
        src = os.path.join(static, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dist, name))
    print(f"  copied static/ ({len(os.listdir(static))} files)")


def _cdn_config(dist: str) -> None:
    # Cloudflare Pages / Netlify rewrites: keep the client's /api/<x> URLs working
    # by serving the frozen <x>.json. Query strings are ignored by the match, which
    # is fine — the snapshots already bake in the right n=.
    redirects = "\n".join(
        f"/api/{name}  /api/{name}.json  200"
        for name in ("meta", "report", "groupadv", "rankings",
                     "news", "bracket", "fixtures")) + "\n"
    with open(os.path.join(dist, "_redirects"), "w", encoding="utf-8") as fh:
        fh.write(redirects)

    # Security + caching headers (the static analogue of server.py's CSP block).
    headers = """/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Frame-Options: DENY
  Content-Security-Policy: default-src 'self'; img-src 'self' https://flagcdn.com data:; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; object-src 'none'

/api/*
  Cache-Control: public, max-age=300, stale-while-revalidate=600
/assets/*
  Cache-Control: public, max-age=86400
"""
    with open(os.path.join(dist, "_headers"), "w", encoding="utf-8") as fh:
        fh.write(headers)

    with open(os.path.join(dist, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(f"User-agent: *\nAllow: /\nSitemap: {PROD_URL}/sitemap.xml\n")

    today = dt.date.today().isoformat()
    with open(os.path.join(dist, "sitemap.xml"), "w", encoding="utf-8") as fh:
        fh.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            f"  <url><loc>{PROD_URL}/</loc><lastmod>{today}</lastmod>"
            "<changefreq>hourly</changefreq><priority>1.0</priority></url>\n"
            f"  <url><loc>{PROD_URL}/about.html</loc><lastmod>{today}</lastmod>"
            "<changefreq>monthly</changefreq><priority>0.3</priority></url>\n"
            "</urlset>\n")
    print("  wrote _redirects, _headers, robots.txt, sitemap.xml")


def _matrix_signature() -> str:
    """A short hash of the live model's behaviour, used to skip the ~4,500-prediction
    matrix rebuild when nothing has changed since the last export (e.g. an export run
    straight after a no-op refresh). Probing the predictor — rather than reaching into
    model internals — means any ratings/param/blend change busts the cache."""
    import hashlib
    p = server.predictor()
    probes = [("Brazil", "Argentina", True), ("France", "England", True),
              ("Spain", "Germany", True), ("Portugal", "Belgium", True),
              ("Japan", "Morocco", True), ("Netherlands", "Croatia", True)]
    rows = []
    for h, a, n in probes:
        try:
            r = p.predict(h, a, neutral=n, log=False)
            rows.append([round(r["p_home"], 6), round(r["p_draw"], 6),
                         round(r["p_away"], 6), round(r["exp_home_goals"], 5),
                         round(r["exp_away_goals"], 5)])
        except Exception as exc:
            rows.append(["err", h, a, n, str(exc)])
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()


def _maybe_export_matrix(api_dir: str) -> None:
    """Write the predict matrix, or reuse the existing one when the model is unchanged
    since the last export to this dir. dist/ is gitignored, so the .matrix_sig marker
    sits harmlessly beside the snapshot and makes repeat deploys (the 30-60 min refresh
    loop) near-instant when a refresh changed nothing."""
    sig_path = os.path.join(api_dir, ".matrix_sig")
    matrix_path = os.path.join(api_dir, "predict_matrix.json")
    sig = _matrix_signature()
    old = None
    try:
        with open(sig_path, encoding="utf-8") as fh:
            old = fh.read().strip()
    except FileNotFoundError:
        pass
    if old == sig and os.path.exists(matrix_path):
        kb = os.path.getsize(matrix_path) / 1024
        print(f"  api/predict_matrix.json  (cached - model unchanged, {kb:.0f} KB)")
        return
    _export_predict_matrix(api_dir)
    with open(sig_path, "w", encoding="utf-8") as fh:
        fh.write(sig)


def build(dist: str = "dist", matrix: bool = True) -> str:
    dist = os.path.abspath(dist)
    api_dir = os.path.join(dist, "api")
    os.makedirs(api_dir, exist_ok=True)
    print(f"Exporting WCPA → {dist}")
    _copy_static(dist)
    _snapshot_endpoints(api_dir)
    _export_history(api_dir)
    if matrix:
        _maybe_export_matrix(api_dir)
    _cdn_config(dist)
    print(f"\nDone. Deploy the contents of {dist} to Cloudflare Pages / Netlify.")
    print(f"Preview locally:  python -m http.server -d {dist} 8009")
    return dist


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "dist"
    build(out, matrix="--no-matrix" not in sys.argv)
