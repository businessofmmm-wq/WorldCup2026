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
from models import collapse_export                # noqa: E402
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


def _export_graph(dist: str) -> None:
    """Regenerate the architecture graph data into the build so the deployed
    /graph page reflects the current source (overwrites the copied placeholder)."""
    try:
        from tools import depgraph
        model = depgraph.build_model(with_health=True)
        depgraph.write_graph_data(model, os.path.join(dist, "graph_data.js"))
        print(f"  graph_data.js  ({model['totals']['modules']} modules)")
    except Exception as exc:                       # never fail a deploy over the graph
        print(f"  graph export skipped: {exc}")


def _copy_static(dist: str) -> None:
    static = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    files = dirs = 0
    for name in os.listdir(static):
        src = os.path.join(static, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(dist, name))
            files += 1
        elif os.path.isdir(src):                 # e.g. static/fonts/ — copy the whole tree
            shutil.copytree(src, os.path.join(dist, name), dirs_exist_ok=True)
            dirs += 1
    print(f"  copied static/ ({files} files, {dirs} dirs)")


def _cdn_config(dist: str) -> None:
    # Cloudflare Pages / Netlify rewrites: keep the client's /api/<x> URLs working
    # by serving the frozen <x>.json. Query strings are ignored by the match, which
    # is fine — the snapshots already bake in the right n=.
    # NOTE on canonical host (www → apex): Pages `_redirects` does NOT support
    # hostname/domain-level source matching (only paths within the site), so the
    # www→apex 301 CANNOT live here — it must be a zone-level Single Redirect /
    # Bulk Redirect (Cloudflare dash → Rules → Redirect Rules: when
    # http.host == "www.wcpa26.com" → 301 concat("https://wcpa26.com",
    # http.request.uri.path)). Without it, www and apex are separate origins with
    # separate caches + localStorage. See the deploy notes / NEXTSTEPS.md.
    redirects = "\n".join(
        f"/api/{name}  /api/{name}.json  200"
        for name in ("meta", "report", "groupadv", "rankings",
                     "news", "bracket", "fixtures",
                     "collapse", "daily")) + "\n"
    with open(os.path.join(dist, "_redirects"), "w", encoding="utf-8") as fh:
        fh.write(redirects)

    # Security + caching headers (the static analogue of server.py's CSP block).
    # CSP is already strict (self-only scripts, no eval); we add HSTS (force HTTPS
    # for a year, incl. subdomains), a locked-down Permissions-Policy (the page
    # needs none of these capabilities), and COOP to isolate the browsing context.
    headers = """/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Frame-Options: DENY
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  Permissions-Policy: accelerometer=(), autoplay=(), camera=(), display-capture=(), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), usb=(), interest-cohort=()
  Cross-Origin-Opener-Policy: same-origin
  Content-Security-Policy: default-src 'self'; img-src 'self' https://flagcdn.com data:; style-src 'self' 'unsafe-inline'; font-src 'self'; script-src 'self' https://challenges.cloudflare.com https://cdnjs.cloudflare.com; connect-src 'self'; frame-src https://challenges.cloudflare.com; base-uri 'none'; frame-ancestors 'none'; object-src 'none'

# HTML is never hard-cached: every visit revalidates, so a redeploy — and the
# new ?v=<hash> asset stamps the fresh HTML points to — is picked up on the very
# next load with no hard-refresh. Stated explicitly rather than relying on a CDN
# default, so two profiles/devices can't drift onto different renders.
/
  Cache-Control: public, max-age=0, must-revalidate
/index.html
  Cache-Control: public, max-age=0, must-revalidate
/about
  Cache-Control: public, max-age=0, must-revalidate
/about.html
  Cache-Control: public, max-age=0, must-revalidate

# Content-hashed bundles. The HTML references these as /app.js?v=<hash>; the URL
# changes whenever the bytes change, so the file itself is safe to cache forever
# (a changed file is a new URL = guaranteed fresh; an unchanged one never
# re-validates = fast repeat loads).
/style.css
  Cache-Control: public, max-age=31536000, immutable
/app.js
  Cache-Control: public, max-age=31536000, immutable
/collapse.js
  Cache-Control: public, max-age=31536000, immutable
/collapse-core.js
  Cache-Control: public, max-age=31536000, immutable

# Data snapshots are rewritten on every deploy. Short max-age + must-revalidate
# (NO stale-while-revalidate) means all visitors converge on the latest numbers
# within ~2 min, instead of one being served a stale copy in the background while
# another already has fresh — the most visible "different version" symptom.
/api/*
  Cache-Control: public, max-age=120, must-revalidate
/assets/*
  Cache-Control: public, max-age=86400
/fonts/*
  Cache-Control: public, max-age=31536000, immutable
"""
    with open(os.path.join(dist, "_headers"), "w", encoding="utf-8") as fh:
        fh.write(headers)

    # robots.txt — classic search engines and social link-preview bots keep full
    # access (SEO + share cards); AI training/scraping crawlers are turned away
    # (the album isn't free training data). This is the polite, standards-based
    # layer; the *enforced* block lives at the Cloudflare edge (Block AI Bots).
    ai_bots = (
        "GPTBot", "ChatGPT-User", "OAI-SearchBot", "anthropic-ai", "ClaudeBot",
        "Claude-Web", "cohere-ai", "PerplexityBot", "CCBot", "Google-Extended",
        "Applebot-Extended", "Bytespider", "Amazonbot", "Meta-ExternalAgent",
        "meta-externalagent", "Meta-ExternalFetcher", "Diffbot", "ImagesiftBot",
        "Omgilibot", "Omgili", "YouBot", "DataForSeoBot", "magpie-crawler",
        "Timpibot", "PetalBot", "Scrapy",
    )
    robots = "# WCPA robots policy — contact: /.well-known/security.txt\n"
    robots += "".join(f"User-agent: {b}\n" for b in ai_bots)
    robots += "Disallow: /\n\nUser-agent: *\nAllow: /\n\n"
    robots += f"Sitemap: {PROD_URL}/sitemap.xml\n"
    with open(os.path.join(dist, "robots.txt"), "w", encoding="utf-8") as fh:
        fh.write(robots)

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

    # RFC 9116 security.txt — a documented disclosure contact. 'Expires' is
    # mandatory and must stay in the future, so recompute it (now + 1 year) on
    # every export. Written to the canonical .well-known path + a root fallback.
    expires = (dt.datetime.now(dt.timezone.utc)
               + dt.timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sec_txt = (f"Contact: mailto:hello@wcpa26.com\n"
               f"Expires: {expires}\n"
               f"Preferred-Languages: en\n"
               f"Canonical: {PROD_URL}/.well-known/security.txt\n")
    well_known = os.path.join(dist, ".well-known")
    os.makedirs(well_known, exist_ok=True)
    for path in (os.path.join(well_known, "security.txt"),
                 os.path.join(dist, "security.txt")):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(sec_txt)

    # Cache-bust: stamp the CSS/JS links in the HTML with a short content hash.
    # The HTML is always revalidated (max-age=0), but /style.css and /app.js are
    # cached for hours by the browser/CDN — versioning the URL means a *changed*
    # file is fetched fresh on the very next load (no hard-refresh) while an
    # unchanged one keeps its long cache. Fixes "my redeploy isn't showing up".
    import hashlib
    def _hash(name):
        with open(os.path.join(dist, name), "rb") as fh:
            return hashlib.md5(fh.read()).hexdigest()[:8]
    # Collapse is an ES module that statically imports ./collapse-core.js; stamp that
    # import with the core's hash so a core change is fetched fresh, then version the
    # entry module by its (now core-aware) content — same cache-bust discipline as app.js.
    cjs = os.path.join(dist, "collapse.js")
    if os.path.exists(cjs) and os.path.exists(os.path.join(dist, "collapse-core.js")):
        core_v = _hash("collapse-core.js")
        with open(cjs, encoding="utf-8") as fh:
            txt = fh.read()
        with open(cjs, "w", encoding="utf-8") as fh:
            fh.write(txt.replace("'./collapse-core.js'", f"'./collapse-core.js?v={core_v}'"))
    css_v, js_v = _hash("style.css"), _hash("app.js")
    coll_v = _hash("collapse.js") if os.path.exists(cjs) else ""
    for html in ("index.html", "about.html"):
        hp = os.path.join(dist, html)
        if not os.path.exists(hp):
            continue
        with open(hp, encoding="utf-8") as fh:
            s = fh.read()
        s = s.replace('href="/style.css"', f'href="/style.css?v={css_v}"')
        s = s.replace('src="/app.js"', f'src="/app.js?v={js_v}"')
        if coll_v:
            s = s.replace('src="/collapse.js"', f'src="/collapse.js?v={coll_v}"')
        with open(hp, "w", encoding="utf-8") as fh:
            fh.write(s)

    print("  wrote _redirects, _headers, robots.txt, sitemap.xml, security.txt; "
          f"versioned css={css_v} js={js_v} collapse={coll_v}")


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
    # Freeze pre-kickoff calls FIRST so the fixtures snapshot below already
    # grades any just-finished match against its stored pre-match prediction.
    try:
        n = server.log_upcoming_calls()
        if n:
            print(f"  froze {n} pre-kickoff call(s) into predictions")
    except Exception as exc:                       # never fail a deploy over this
        print(f"  pre-kickoff call logging skipped: {exc}")
    # drop artefacts a previous export wrote but this build no longer produces
    shutil.rmtree(os.path.join(api_dir, "tactics"), ignore_errors=True)
    for stale in ("tactics_index.json",):
        try:
            os.remove(os.path.join(api_dir, stale))
        except FileNotFoundError:
            pass
    _copy_static(dist)
    _export_graph(dist)
    _snapshot_endpoints(api_dir)
    _export_history(api_dir)
    _p = server.predictor()
    collapse_export.export_collapse(api_dir, _p)   # Collapse run game — live snapshot
    collapse_export.export_daily(api_dir, _p)      # Collapse daily challenge (frozen)
    if matrix:
        _maybe_export_matrix(api_dir)
    _cdn_config(dist)
    print(f"\nDone. Deploy the contents of {dist} to Cloudflare Pages / Netlify.")
    print(f"Preview locally:  python -m http.server -d {dist} 8009")
    return dist


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "dist"
    build(out, matrix="--no-matrix" not in sys.argv)
