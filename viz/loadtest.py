#!/usr/bin/env python
"""Stdlib load tester for the static WCPA build — proof it survives a World-Cup
traffic spike. No ab / wrk / locust; pure standard library.

    python run.py loadtest                       serve ./dist, hammer key paths
    python run.py loadtest dist 8011             serve a given dir on a given port
    python run.py loadtest http://127.0.0.1:8009 hit an already-running target
    python run.py loadtest -n 4000 -c 64         4000 requests across 64 workers

The public site is a static CDN export, so this measures the *worst case*: a single
Python http.server process on this PC. A real CDN (Cloudflare Pages) fans the same
files out across hundreds of edge nodes, so production headroom is far larger than
the numbers below — if one local process holds up, the edge certainly will.
"""
from __future__ import annotations
import http.client
import os
import sys
import threading
import time
from collections import Counter
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Representative request mix. The ~4 MB predict_matrix is included but it is fetched
# once per visitor (lazily, for the Match Lab), so one slot in the rotation is plenty.
PATHS = [
    "/", "/app.js", "/style.css", "/about.html",
    "/api/meta.json", "/api/report.json", "/api/groupadv.json",
    "/api/rankings.json", "/api/fixtures.json", "/api/bracket.json",
    "/api/news.json", "/api/history.json",
    "/api/predict_matrix.json",
]


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # keep the load-test output clean
        pass


def _serve(directory: str, port: int) -> ThreadingHTTPServer:
    handler = partial(_QuietHandler, directory=os.path.abspath(directory))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def _pct(ms_sorted, q):
    if not ms_sorted:
        return 0.0
    return ms_sorted[min(len(ms_sorted) - 1, int(q * len(ms_sorted)))]


def _worker(host, port, secure, n, paths, lat, errs, idx, lock):
    mk = http.client.HTTPSConnection if secure else http.client.HTTPConnection
    conn = mk(host, port, timeout=15)
    while True:
        with lock:
            i = idx[0]
            if i >= n:
                break
            idx[0] += 1
        path = paths[i % len(paths)]
        t0 = time.perf_counter()
        try:
            conn.request("GET", path)
            resp = conn.getresponse()
            resp.read()                      # drain so the connection can be reused
            lat.append((time.perf_counter() - t0) * 1000.0)
            if resp.status >= 400:
                errs.append((path, resp.status))
        except Exception as exc:
            errs.append((path, type(exc).__name__))
            try:                              # reconnect on a dropped socket
                conn.close()
                conn = mk(host, port, timeout=15)
            except Exception:
                pass
    conn.close()


def run(target: str, n: int = 2000, c: int = 32, paths=PATHS) -> dict:
    pr = urlparse(target)
    secure = pr.scheme == "https"
    host = pr.hostname or "127.0.0.1"
    port = pr.port or (443 if secure else 80)
    lat, errs, idx, lock = [], [], [0], threading.Lock()
    threads = [threading.Thread(
        target=_worker, args=(host, port, secure, n, paths, lat, errs, idx, lock))
        for _ in range(c)]
    t0 = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - t0 or 1e-9
    lat.sort()
    done = len(lat)
    print(f"\n  target      {target}")
    print(f"  requests    {done} ok / {len(errs)} errors   (concurrency {c})")
    print(f"  elapsed     {elapsed:.2f}s")
    print(f"  throughput  {done / elapsed:,.0f} req/s")
    if lat:
        print(f"  latency ms  p50 {_pct(lat, .5):.1f}   p90 {_pct(lat, .9):.1f}   "
              f"p99 {_pct(lat, .99):.1f}   max {lat[-1]:.1f}")
    else:
        print("  latency     n/a (every request failed — is the target up?)")
    if errs:
        print(f"  top errors  {Counter(str(e[1]) for e in errs).most_common(5)}")
    print()
    return {"ok": done, "errors": len(errs), "rps": done / elapsed}


def main(args):
    n, c, pos, i = 2000, 32, [], 0
    while i < len(args):
        a = args[i]
        if a == "-n" and i + 1 < len(args):
            n = int(args[i + 1]); i += 2
        elif a == "-c" and i + 1 < len(args):
            c = int(args[i + 1]); i += 2
        else:
            pos.append(a); i += 1

    httpd = None
    if pos and pos[0].startswith("http"):
        target = pos[0].rstrip("/")
    else:
        directory = pos[0] if pos else "dist"
        port = int(pos[1]) if len(pos) > 1 and pos[1].isdigit() else 8011
        if not os.path.isdir(directory):
            print(f"no such dir: {directory!r} — run `python run.py export {directory}` first")
            return
        kb = sum(os.path.getsize(os.path.join(dp, f))
                 for dp, _, fs in os.walk(directory) for f in fs) // 1024
        httpd = _serve(directory, port)
        target = f"http://127.0.0.1:{port}"
        time.sleep(0.3)                       # let the listener bind
        print(f"serving {directory}/ ({kb} KB) at {target}")

    print(f"load test: {n} requests, {c} concurrent, over {len(PATHS)} paths")
    try:
        run(target, n=n, c=c)
    finally:
        if httpd:
            httpd.shutdown()


if __name__ == "__main__":
    main(sys.argv[1:])
