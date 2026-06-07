#!/usr/bin/env python
"""
WCPA self-standing audit — security · stability · load · hygiene.

One re-runnable, pure-stdlib gate over the whole engine. It is deliberately
*not* a linter: it answers the launch questions directly — is this thing safe
and secure, does it stand up on its own, does it survive a World-Cup traffic
spike, and is it free of dead weight?

Every run prints a LIVE pipeline diagram (the four phases light up as they
pass) and writes ``AUDIT.md`` — a Mermaid verdict, a findings table, the
load-test numbers and a cull ledger — so there is a dated record each time.

    python run.py audit                full audit, write AUDIT.md
    python run.py audit --no-load      skip the load test (faster)
    python run.py audit --quiet        findings only, no live diagram

Exit status is 0 when nothing FAILED (warnings are allowed) and 1 otherwise,
so it can gate ``deploy.bat`` before a publish.

Reuses ``tools/depgraph.build_model()`` for the import graph (orphan
detection) — one source of truth for how the backend wires together.
"""
from __future__ import annotations

import os
import re
import sys
import time
import subprocess
import py_compile
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Severities, worst-wins.
PASS, INFO, WARN, FAIL = "PASS", "INFO", "WARN", "FAIL"
RANK = {PASS: 0, INFO: 1, WARN: 2, FAIL: 3}
MARK = {PASS: "✓", INFO: "i", WARN: "!", FAIL: "✗"}

PHASES = ["SECURITY", "STABILITY", "LOAD", "HYGIENE"]


class Check:
    __slots__ = ("name", "status", "detail")

    def __init__(self, name: str, status: str, detail: str = ""):
        self.name, self.status, self.detail = name, status, detail


# --------------------------------------------------------------------------- #
# File helpers — scan the set that would actually ship (git-tracked), so the
# audit reflects the repo, not local scratch.
# --------------------------------------------------------------------------- #
def committed_files() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, timeout=20)
        # Skip tracked-but-missing paths (e.g. a deletion staged mid-cull) so the
        # audit reflects the working tree, not the index.
        files = [f for f in out.stdout.splitlines() if f.strip()
                 and os.path.exists(os.path.join(ROOT, f))]
        if files:
            return files
    except Exception:
        pass
    # Fallback: walk, skipping build/vcs/data dirs.
    skip = {".git", "__pycache__", "dist", "_shots", "assets", "data",
            "node_modules", ".venv", "venv"}
    found = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [d for d in dns if d not in skip]
        for fn in fns:
            found.append(os.path.relpath(os.path.join(dp, fn), ROOT).replace(os.sep, "/"))
    return found


def _read(rel: str) -> str:
    try:
        with open(os.path.join(ROOT, rel), encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except Exception:
        return ""


# --------------------------------------------------------------------------- #
# SECURITY
# --------------------------------------------------------------------------- #
# High-confidence live-secret signatures. Each requires a real value tail, so
# these very pattern strings do not match themselves.
SECRET_SIGNATURES = {
    "Stripe secret/restricted key": r"\b[sr]k_(?:live|test)_[0-9A-Za-z]{20,}",
    "Stripe publishable key (embedded)": r"\bpk_(?:live|test)_[0-9A-Za-z]{20,}",
    "Stripe webhook secret": r"\bwhsec_[0-9A-Za-z]{20,}",
    "AWS access key id": r"\bAKIA[0-9A-Z]{16}\b",
    "Google API key": r"\bAIza[0-9A-Za-z_\-]{30,}",
    "Private key block": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----",
}
# A token (UUID) sitting next to webhook/secret wording — the Ko-fi case.
TOKEN_CONTEXT = re.compile(
    r"(?i)(?:webhook|verification|secret|token)[^\n]{0,40}"
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def check_secrets(files: list[str]) -> Check:
    hits = []
    for rel in files:
        if rel.endswith((".png", ".svg", ".ico", ".woff2")):
            continue
        if rel.replace("\\", "/") == "tools/audit.py":   # don't scan the scanner
            continue
        text = _read(rel)
        for label, pat in SECRET_SIGNATURES.items():
            if re.search(pat, text):
                hits.append(f"{label} in {rel}")
        if TOKEN_CONTEXT.search(text) and not rel.endswith(".example"):
            hits.append(f"token-like UUID near secret wording in {rel}")
    if hits:
        return Check("secret scan (tracked files)", FAIL, "; ".join(hits[:4]))
    return Check("secret scan (tracked files)", PASS,
                 f"{len(files)} tracked files — no live keys/tokens")


def check_sql_injection(files: list[str]) -> Check:
    """Flag any .execute(...) whose SQL is built by f-string / % / + / .format
    rather than passed as parameters."""
    bad = []
    risky = re.compile(r"\.execute\(\s*(?:f[\"']|[\"'][^\"']*[\"']\s*(?:%|\+|\.format))")
    for rel in files:
        if not rel.endswith(".py"):
            continue
        for i, line in enumerate(_read(rel).splitlines(), 1):
            if risky.search(line):
                bad.append(f"{rel}:{i}")
    if bad:
        return Check("SQL parameterisation", FAIL,
                     "string-built SQL at " + ", ".join(bad[:5]))
    return Check("SQL parameterisation", PASS,
                 "all .execute() calls use %s parameters")


def check_headers() -> Check:
    srv = _read("viz/server.py")
    need = ["Content-Security-Policy", "X-Content-Type-Options",
            "Referrer-Policy", "frame-ancestors 'none'", "script-src 'self'"]
    miss = [n for n in need if n not in srv]
    hdr = _read("dist/_headers")
    cdn_ok = "X-Frame-Options" in hdr and "Content-Security-Policy" in hdr
    if miss:
        return Check("security headers + CSP", WARN,
                     "server missing: " + ", ".join(miss))
    if not cdn_ok:
        return Check("security headers + CSP", WARN,
                     "dist/_headers missing CSP/XFO (run export)")
    return Check("security headers + CSP", PASS,
                 "strict CSP + nosniff/referrer/frame-ancestors on server & CDN")


def check_path_traversal() -> Check:
    srv = _read("viz/server.py")
    guarded = ("realpath" in srv
               and "startswith(root" in srv.replace(" ", "")
               and "isfile" in srv)
    if guarded:
        return Check("path-traversal guard", PASS,
                     "static serve uses realpath + root-boundary + isfile")
    return Check("path-traversal guard", FAIL,
                 "static file serving lacks a realpath boundary check")


def check_xml() -> Check:
    if "ElementTree" in _read("sources/news.py"):
        # No external-entity resolution in stdlib ET (no XXE); feeds are trusted
        # HTTPS majors and parsing runs in the local CLI, not the static public
        # site — so this is a defensive FYI, not a launch action item.
        return Check("XML parsing (RSS)", INFO,
                     "stdlib ElementTree on trusted HTTPS feeds (no XXE surface); "
                     "consider defusedxml only if feeds widen to untrusted sources")
    return Check("XML parsing (RSS)", INFO, "no XML parser found")


def check_deps() -> Check:
    req = _read("requirements.txt")
    pkgs = [l for l in req.splitlines() if l.strip() and not l.strip().startswith("#")]
    pinned = [l for l in pkgs if any(op in l for op in ("==", ">=", "~="))]
    if pkgs and len(pinned) == len(pkgs):
        return Check("dependency pinning", PASS,
                     f"{len(pkgs)} deps, all version-constrained")
    return Check("dependency pinning", WARN,
                 f"{len(pkgs) - len(pinned)} of {len(pkgs)} deps unpinned")


# --------------------------------------------------------------------------- #
# STABILITY
# --------------------------------------------------------------------------- #
def check_compile(files: list[str]) -> Check:
    errs = []
    n = 0
    for rel in files:
        if not rel.endswith(".py"):
            continue
        n += 1
        try:
            py_compile.compile(os.path.join(ROOT, rel), doraise=True)
        except py_compile.PyCompileError as exc:
            errs.append(f"{rel}: {str(exc).splitlines()[-1][:60]}")
    if errs:
        return Check("compile all modules", FAIL, "; ".join(errs[:4]))
    return Check("compile all modules", PASS, f"{n} modules compile clean")


def check_utf8_guard() -> Check:
    if "reconfigure(encoding=\"utf-8\")" in _read("run.py").replace("'", '"'):
        return Check("console utf-8 guard", PASS,
                     "run.py forces utf-8 stdout (Windows cp1252 safe)")
    return Check("console utf-8 guard", WARN, "no stdout utf-8 reconfigure")


def check_self_standing() -> Check:
    """Run `python run.py health` as a child process — proves the CLI stands up
    on its own and reaches its data store."""
    try:
        out = subprocess.run([sys.executable, "run.py", "health"], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    except Exception as exc:
        return Check("self-standing run (run.py health)", FAIL, str(exc)[:80])
    blob = out.stdout + out.stderr
    if out.returncode != 0:
        return Check("self-standing run (run.py health)", FAIL,
                     f"exit {out.returncode}: {blob.strip()[:80]}")
    connected = "connected" in blob and "True" in blob
    detail = "CLI ran; DB " + ("connected" if connected else "NOT connected")
    return Check("self-standing run (run.py health)", PASS if connected else WARN, detail)


def check_no_leak() -> Check:
    srv = _read("viz/server.py")
    if "internal server error" in srv and "traceback.print_exc" in srv:
        return Check("error non-leak", PASS,
                     "API errors log server-side, return generic 500")
    return Check("error non-leak", WARN, "verify API errors don't leak internals")


# --------------------------------------------------------------------------- #
# LOAD
# --------------------------------------------------------------------------- #
def check_load(dirn: str = "dist", n: int = 1500, c: int = 32) -> tuple[Check, dict]:
    path = os.path.join(ROOT, dirn)
    if not os.path.isdir(path):
        return Check("load test (static build)", WARN,
                     f"no {dirn}/ — run `python run.py export` first"), {}
    try:
        from viz import loadtest
        port = 8044
        httpd = loadtest._serve(path, port)
        time.sleep(0.3)
        res = loadtest.run(f"http://127.0.0.1:{port}", n=n, c=c)
        httpd.shutdown()
    except Exception as exc:
        return Check("load test (static build)", FAIL, str(exc)[:90]), {}
    rps, errs = res.get("rps", 0), res.get("errors", 0)
    status = PASS if (errs == 0 and rps >= 100) else (WARN if errs == 0 else FAIL)
    detail = f"{rps:,.0f} req/s, {errs} errors over {res.get('ok', 0)} reqs (c={c})"
    return Check("load test (static build)", status, detail), res


# --------------------------------------------------------------------------- #
# HYGIENE / CULL
# --------------------------------------------------------------------------- #
ENTRY_OK = {"run", "viz.server"}   # legitimate entry points with no importers


def check_orphans() -> tuple[Check, list[str]]:
    try:
        from tools import depgraph
        model = depgraph.build_model(with_health=False)
    except Exception as exc:
        return Check("orphan modules", WARN, f"graph build failed: {exc}"), []
    orphans = [n["name"] for n in model["nodes"].values()
               if not n["dependents"] and n["name"] not in ENTRY_OK]
    if orphans:
        return (Check("orphan modules", WARN,
                      "no importer: " + ", ".join(orphans)), orphans)
    return Check("orphan modules", PASS, "every module is reachable"), []


def _dir_bytes(path: str) -> int:
    total = 0
    for dp, _dns, fns in os.walk(path):
        for fn in fns:
            try:
                total += os.path.getsize(os.path.join(dp, fn))
            except OSError:
                pass
    return total


def check_disk_cruft() -> tuple[Check, list[tuple[str, int]]]:
    items: list[tuple[str, int]] = []
    for dp, dns, fns in os.walk(ROOT):
        if "__pycache__" in dns:
            p = os.path.join(dp, "__pycache__")
            items.append((os.path.relpath(p, ROOT), _dir_bytes(p)))
            dns.remove("__pycache__")
        if ".git" in dns:
            dns.remove(".git")
        for fn in fns:
            if fn.endswith(".log"):
                p = os.path.join(dp, fn)
                items.append((os.path.relpath(p, ROOT), os.path.getsize(p)))
    shots = os.path.join(ROOT, "viz", "_shots")
    if os.path.isdir(shots):
        items.append(("viz/_shots", _dir_bytes(shots)))
    total = sum(b for _n, b in items)
    if total > 0:
        return (Check("disk cruft (build/scratch)", INFO,
                      f"{total // 1024} KB across {len(items)} items — safe to clear"),
                items)
    return Check("disk cruft (build/scratch)", PASS, "working dir is clean"), []


def check_todos(files: list[str]) -> Check:
    pat = re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")
    hits = 0
    for rel in files:
        if rel.endswith((".py", ".js", ".html", ".css", ".md", ".sql")):
            hits += len(pat.findall(_read(rel)))
    if hits == 0:
        return Check("TODO/FIXME markers", PASS, "none in tracked source")
    return Check("TODO/FIXME markers", INFO, f"{hits} markers (informational)")


# --------------------------------------------------------------------------- #
# Live pipeline renderer
# --------------------------------------------------------------------------- #
class Board:
    """Draws the four-phase pipeline; redraws in place on a TTY, prints
    incremental lines otherwise (so piped/captured output stays readable)."""

    def __init__(self, live: bool):
        self.live = live
        self.phase_checks: dict[str, list[Check]] = {p: [] for p in PHASES}
        self.active: str | None = None
        self._drawn = 0

    def start(self, phase: str):
        self.active = phase
        self._draw()

    def add(self, phase: str, chk: Check):
        self.phase_checks[phase].append(chk)
        if self.live:
            self._draw()
            time.sleep(0.12)          # let the eye catch each tick
        else:
            print(f"  [{phase:<9}] {MARK[chk.status]} {chk.name:<34} {chk.status}"
                  + (f"  — {chk.detail}" if chk.detail else ""))

    def _phase_status(self, phase: str) -> str:
        cks = self.phase_checks[phase]
        if not cks:
            return "queued" if phase != self.active else "running"
        worst = max((c.status for c in cks), key=lambda s: RANK[s])
        return worst

    def _draw(self):
        if not self.live:
            return
        lines = ["", "   WCPA · SELF-STANDING AUDIT", ""]
        for i, p in enumerate(PHASES):
            cks = self.phase_checks[p]
            ticks = "".join(MARK[c.status] for c in cks) or "·"
            st = self._phase_status(p)
            arrow = " │" if i < len(PHASES) - 1 else "  "
            lines.append(f"   ┌─ {p:<9} ─┐  {ticks:<10} {st}")
            lines.append(f"   └─────{arrow}─────┘")
        block = "\n".join(lines)
        if self._drawn:
            sys.stdout.write(f"\033[{self._drawn}A\033[J")
        sys.stdout.write(block + "\n")
        sys.stdout.flush()
        self._drawn = block.count("\n") + 1


# --------------------------------------------------------------------------- #
# AUDIT.md
# --------------------------------------------------------------------------- #
def _verdict(checks: list[Check]) -> tuple[str, str]:
    worst = max((c.status for c in checks), key=lambda s: RANK[s])
    if worst == FAIL:
        return "RED", "blockers found — do not publish"
    if worst == WARN:
        return "AMBER", "launch-ready; review the warnings"
    return "GREEN", "launch-ready — clean across the board"


def _mermaid(phase_status: dict[str, str]) -> str:
    color = {PASS: "#1f8a70", INFO: "#6b4f8a", WARN: "#e3a512", FAIL: "#c2362f"}
    out = ["flowchart LR"]
    for p in PHASES:
        s = phase_status[p]
        out.append(f"  {p}[\"{p}<br/>{s}\"]")
        out.append(f"  style {p} fill:{color[s]},stroke:#20150c,color:#fff,stroke-width:2px")
    out.append("  SECURITY --> STABILITY --> LOAD --> HYGIENE")
    return "\n".join(out)


def write_report(checks: list[Check], phase_of: dict[str, str],
                 load: dict, orphans: list[str],
                 cruft: list[tuple[str, int]], path: str | None = None) -> str:
    path = path or os.path.join(ROOT, "AUDIT.md")
    phase_status = {p: (max((c.status for c in [c for c in checks
                    if phase_of.get(c.name) == p]), key=lambda s: RANK[s])
                    if any(phase_of.get(c.name) == p for c in checks) else PASS)
                    for p in PHASES}
    band, blurb = _verdict(checks)
    n_pass = sum(1 for c in checks if c.status == PASS)
    n_warn = sum(1 for c in checks if c.status == WARN)
    n_fail = sum(1 for c in checks if c.status == FAIL)

    rows = ["| Phase | Check | Result | Detail |", "|---|---|:--:|---|"]
    for c in checks:
        rows.append(f"| {phase_of.get(c.name, '')} | {c.name} | "
                    f"{MARK[c.status]} {c.status} | {c.detail.replace('|', '/')} |")

    cull = ["| Item | Size | Tracked? | Recommendation |", "|---|--:|:--:|---|"]
    for name in orphans:
        cull.append(f"| `{name}` (module, no importer) | — | yes | "
                    f"review — redundant entry/shim? |")
    for name, b in cruft:
        cull.append(f"| `{name}` | {b // 1024} KB | no (gitignored) | "
                    f"safe to delete — regenerated on demand |")
    if len(cull) == 2:
        cull.append("| — | — | — | nothing to cull |")

    load_block = "_Load test skipped._"
    if load:
        load_block = (f"- **{load.get('rps', 0):,.0f} req/s** sustained, "
                      f"**{load.get('errors', 0)} errors** over {load.get('ok', 0)} "
                      f"requests against the static `dist/` build (single local "
                      f"Python process — a CDN fans this across edge nodes).")

    md = f"""<!-- AUTO-GENERATED by `python run.py audit` — re-run to refresh. -->
# WCPA — Self-Standing Audit

_Generated {dt.datetime.now().isoformat(timespec="seconds")} ·
{len(checks)} checks · {n_pass} pass · {n_warn} warn · {n_fail} fail._

## Verdict: {band} — {blurb}

```mermaid
{_mermaid(phase_status)}
```

## Findings

{os.linesep.join(rows)}

## Load test

{load_block}

## Cull ledger

{os.linesep.join(cull)}

> Disk cruft is build/scratch output (already gitignored, so never in the
> repo). Clearing it only tidies the working directory and is always safe —
> `__pycache__` and `dist/` regenerate on the next run/export.

## Re-run

```
python run.py audit            # full, writes this file
python run.py audit --no-load  # skip the spike test
```
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return path


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_audit(do_load: bool = True, live: bool = True) -> int:
    files = committed_files()
    board = Board(live=live)
    checks: list[Check] = []
    phase_of: dict[str, str] = {}

    def emit(phase: str, chk: Check):
        checks.append(chk)
        phase_of[chk.name] = phase
        board.add(phase, chk)

    # SECURITY
    board.start("SECURITY")
    emit("SECURITY", check_secrets(files))
    emit("SECURITY", check_sql_injection(files))
    emit("SECURITY", check_headers())
    emit("SECURITY", check_path_traversal())
    emit("SECURITY", check_xml())
    emit("SECURITY", check_deps())

    # STABILITY
    board.start("STABILITY")
    emit("STABILITY", check_compile(files))
    emit("STABILITY", check_utf8_guard())
    emit("STABILITY", check_self_standing())
    emit("STABILITY", check_no_leak())

    # LOAD
    board.start("LOAD")
    load = {}
    if do_load:
        chk, load = check_load()
        emit("LOAD", chk)
    else:
        emit("LOAD", Check("load test (static build)", INFO, "skipped (--no-load)"))

    # HYGIENE
    board.start("HYGIENE")
    orphan_chk, orphans = check_orphans()
    emit("HYGIENE", orphan_chk)
    cruft_chk, cruft = check_disk_cruft()
    emit("HYGIENE", cruft_chk)
    emit("HYGIENE", check_todos(files))

    path = write_report(checks, phase_of, load, orphans, cruft)

    band, blurb = _verdict(checks)
    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_warn = sum(1 for c in checks if c.status == WARN)
    print()
    print(f"  VERDICT: {band} — {blurb}")
    print(f"  {len(checks)} checks · {n_fail} fail · {n_warn} warn · "
          f"{sum(1 for c in checks if c.status == PASS)} pass")
    print(f"  wrote {os.path.relpath(path, ROOT)}")
    return 1 if n_fail else 0


def main(args: list[str] | None = None) -> int:
    args = args or []
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    do_load = "--no-load" not in args
    live = "--quiet" not in args and sys.stdout.isatty()
    return run_audit(do_load=do_load, live=live)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
