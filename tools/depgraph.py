#!/usr/bin/env python
"""
Connected-graph of the World Cup 2026 backend — pure-stdlib, AST-driven.

Honouring the project's tiny-deps ethos (no pydeps, no graphviz, no networkx),
this walks every project ``.py`` file, parses it with the standard-library ``ast``
module, and reconstructs how the backend wires together:

  * intra-project imports               (who depends on whom)
  * each module's role                  (read live from its docstring)
  * which modules touch PostgreSQL      (import db / psycopg)
  * which modules reach the network      (import requests / urllib)
  * the live HTTP endpoints             (viz/server.py ROUTES)
  * the CLI commands                    (run.py COMMANDS)

…then emits two views you can open straight in VS Code:

  1. ``ARCHITECTURE.md`` — a Mermaid dependency graph + a curated data-flow
     pipeline + a module table + a LIVE database snapshot. Renders in VS Code's
     Markdown preview (with the Mermaid extension) and natively on GitHub.
  2. ``viz/static/graph_data.js`` — the same graph as data for the interactive
     ``/graph`` page (hand-rolled SVG, draggable, live DB overlay).

    python run.py graph            # write both, print a summary + live snapshot
    python run.py graph --md       # only ARCHITECTURE.md
    python run.py graph --data     # only the graph_data.js for the web page

The graph is "live" in two senses: it is regenerated from the *current* source
every run (rename a module and the graph follows), and it embeds a real-time
``db.health()`` snapshot so the picture reflects the actual data behind it.
"""
from __future__ import annotations

import ast
import datetime as dt
import json
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories we never treat as source (data/build artefacts, vcs, the venv, and
# this tools/ package itself — the graph is about the product, not its scaffolding).
SKIP_DIRS = {".git", "__pycache__", "data", "dist", "tools", ".venv", "venv",
             "_shots", "assets", "node_modules"}

# --------------------------------------------------------------------------- #
# Layers — drives grouping, ordering and colour in both the Mermaid graph and
# the interactive page. Colours echo the dashboard's retro-terrace palette.
# --------------------------------------------------------------------------- #
LAYERS = {
    "entry":    {"label": "Entry points",  "fill": "#e3a512", "stroke": "#7a5a06", "text": "#20150c"},
    "core":     {"label": "Core",          "fill": "#3a2a1a", "stroke": "#20150c", "text": "#f3e7c8"},
    "sources":  {"label": "Data sources",  "fill": "#1f8a70", "stroke": "#0f5a47", "text": "#ffffff"},
    "models":   {"label": "Models",        "fill": "#243b6b", "stroke": "#152b52", "text": "#ffffff"},
    "viz":      {"label": "Visualisation", "fill": "#d2541b", "stroke": "#8f3710", "text": "#ffffff"},
    "external": {"label": "External",      "fill": "#e8d8b2", "stroke": "#8a7647", "text": "#20150c"},
    "store":    {"label": "Data store",    "fill": "#6b4f8a", "stroke": "#43305a", "text": "#ffffff"},
}
LAYER_ORDER = ["entry", "sources", "core", "store", "models", "viz", "external"]

# Modules that are entry points regardless of their package.
ENTRY_MODULES = {"run", "viz.server"}


# --------------------------------------------------------------------------- #
# Discovery + parsing
# --------------------------------------------------------------------------- #
def _module_name(path: str) -> tuple[str, bool]:
    """(dotted name, is_package) for a .py file relative to ROOT."""
    rel = os.path.relpath(path, ROOT).replace(os.sep, "/")[:-3]  # drop .py
    if rel.endswith("/__init__"):
        return rel[: -len("/__init__")].replace("/", "."), True
    return rel.replace("/", "."), False


def discover() -> dict[str, dict]:
    """Find every project module → {path, name, is_package, loc, source, tree}."""
    mods: dict[str, dict] = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            name, is_pkg = _module_name(full)
            with open(full, encoding="utf-8") as fh:
                src = fh.read()
            mods[name] = {
                "name": name, "path": full, "is_package": is_pkg,
                "loc": src.count("\n") + 1, "source": src,
                "tree": ast.parse(src, filename=full),
            }
    return mods


def _package_of(name: str, is_pkg: bool) -> str:
    """The package context used to resolve relative imports inside a module."""
    if is_pkg:
        return name
    return name.rsplit(".", 1)[0] if "." in name else ""


def _resolve(target: str, known: set[str]) -> str | None:
    """Longest dotted prefix of *target* that is a known local module, else None."""
    parts = target.split(".")
    for i in range(len(parts), 0, -1):
        cand = ".".join(parts[:i])
        if cand in known:
            return cand
    return None


def local_imports(mod: dict, known: set[str]) -> set[str]:
    """Set of project modules that *mod* imports (resolved, self-edges dropped)."""
    deps: set[str] = set()
    pkg = _package_of(mod["name"], mod["is_package"])
    for node in ast.walk(mod["tree"]):
        if isinstance(node, ast.Import):
            for a in node.names:
                hit = _resolve(a.name, known)
                if hit:
                    deps.add(hit)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — climb the package tree
                base_parts = pkg.split(".") if pkg else []
                up = node.level - 1
                base_parts = base_parts[: len(base_parts) - up] if up else base_parts
                base = ".".join(base_parts)
                base = f"{base}.{node.module}" if node.module else base
            else:
                base = node.module or ""
            # `from pkg import name` may import a submodule (pkg.name) or a symbol.
            for a in node.names:
                hit = _resolve(f"{base}.{a.name}", known) or _resolve(base, known)
                if hit:
                    deps.add(hit)
    deps.discard(mod["name"])
    return deps


def _raw_imports(mod: dict) -> set[str]:
    """Top-level imported names (for spotting requests / psycopg / urllib)."""
    out: set[str] = set()
    for node in ast.walk(mod["tree"]):
        if isinstance(node, ast.Import):
            out.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module.split(".")[0])
    return out


def _role(mod: dict) -> str:
    """First sentence of the module docstring — the role, read live from code."""
    doc = ast.get_docstring(mod["tree"]) or ""
    doc = " ".join(doc.split())
    if not doc:
        return ""
    # first sentence, trimmed to a sensible length
    sentence = re.split(r"(?<=[.!?])\s", doc)[0]
    return (sentence[:117] + "…") if len(sentence) > 118 else sentence


def _layer(name: str) -> str:
    if name in ENTRY_MODULES:
        return "entry"
    if name in ("config", "db"):
        return "core"
    top = name.split(".")[0]
    return {"sources": "sources", "models": "models", "viz": "viz"}.get(top, "core")


# --------------------------------------------------------------------------- #
# Source-level facts (endpoints, CLI commands) — read by regex, no imports run.
# --------------------------------------------------------------------------- #
def endpoints(mods: dict[str, dict]) -> list[str]:
    src = mods.get("viz.server", {}).get("source", "")
    return sorted(set(re.findall(r'"(/api/[a-z]+)"\s*:', src)))


def cli_commands(mods: dict[str, dict]) -> list[str]:
    src = mods.get("run", {}).get("source", "")
    # keys in the COMMANDS dict: "<name>": cmd_<name>
    return sorted(set(re.findall(r'"([a-z]+)"\s*:\s*cmd_', src)))


# External systems each source/sink talks to (annotated edges, not code imports).
EXTERNALS = {
    "sources.results":   ("ext_martj42",   "martj42 results CSV", "49k internationals since 1872"),
    "sources.sportsdb":  ("ext_sportsdb",  "TheSportsDB API",     "live 2026 fixtures & scores"),
    "sources.statsbomb": ("ext_statsbomb", "StatsBomb open data", "shot-level xG"),
    "sources.news":      ("ext_rss",       "News RSS",            "BBC · Guardian · Sky · ESPN"),
}


# --------------------------------------------------------------------------- #
# Build the graph model
# --------------------------------------------------------------------------- #
def build_model(with_health: bool = True) -> dict:
    mods = discover()
    known = set(mods)

    # keep real modules; drop empty package __init__ files (pure markers)
    nodes: dict[str, dict] = {}
    for name, m in mods.items():
        body = [n for n in m["tree"].body if not isinstance(n, ast.Expr)]
        if m["is_package"] and not body:
            continue
        deps = local_imports(m, known)
        raw = _raw_imports(m)
        nodes[name] = {
            "id": name.replace(".", "_"), "name": name, "layer": _layer(name),
            "loc": m["loc"], "role": _role(m), "deps": sorted(deps),
            "db": ("db" in deps) or ("psycopg" in raw),
            "net": bool(raw & {"requests", "urllib", "http"}) and name != "viz.server",
        }

    # fill dependents (reverse edges) for the interactive highlight
    for n in nodes.values():
        n["dependents"] = []
    for n in nodes.values():
        for d in n["deps"]:
            if d in nodes:
                nodes[d]["dependents"].append(n["name"])

    edges = [{"from": n["name"], "to": d, "kind": "import"}
             for n in nodes.values() for d in n["deps"] if d in nodes]

    health = {}
    sim = {}
    if with_health:
        try:
            import sys
            if ROOT not in sys.path:
                sys.path.insert(0, ROOT)
            import db  # noqa: E402  (local import; only when a snapshot is wanted)
            health = db.health()
        except Exception as exc:
            health = {"connected": False, "error": str(exc)}
        try:
            with open(os.path.join(ROOT, "data", "sim_report.json"), encoding="utf-8") as fh:
                rep = json.load(fh)
            sim = {"runs": rep.get("runs"), "generated": rep.get("generated"),
                   "leader": (rep.get("title_odds") or [{}])[0].get("team")}
        except Exception:
            pass

    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "nodes": nodes, "edges": edges,
        "endpoints": endpoints(mods), "commands": cli_commands(mods),
        "externals": EXTERNALS, "health": health, "sim": sim,
        "totals": {"modules": len(nodes),
                   "loc": sum(n["loc"] for n in nodes.values()),
                   "edges": len(edges)},
    }


# --------------------------------------------------------------------------- #
# Mermaid rendering (→ ARCHITECTURE.md)
# --------------------------------------------------------------------------- #
def _mermaid_dependency(model: dict) -> str:
    nodes = model["nodes"]
    out = ["flowchart LR"]
    for key, st in LAYERS.items():
        out.append(f"  classDef {key} fill:{st['fill']},stroke:{st['stroke']},"
                   f"color:{st['text']},stroke-width:2px;")
    out.append("  classDef ext fill:#e8d8b2,stroke:#8a7647,color:#20150c,"
               "stroke-width:1.5px,stroke-dasharray:4 3;")

    # group module nodes into subgraphs by layer
    by_layer: dict[str, list[dict]] = {}
    for n in nodes.values():
        by_layer.setdefault(n["layer"], []).append(n)
    for layer in LAYER_ORDER:
        items = by_layer.get(layer)
        if not items:
            continue
        out.append(f'  subgraph L_{layer}["{LAYERS[layer]["label"]}"]')
        out.append("    direction TB")
        for n in sorted(items, key=lambda x: x["name"]):
            badge = ("  ⛁" if n["db"] else "") + ("  🌐" if n["net"] else "")
            out.append(f'    {n["id"]}["{n["name"]}<br/>{n["loc"]} LOC{badge}"]')
        out.append("  end")

    # external systems + the data store
    out.append('  PG[("PostgreSQL<br/>worldcup")]')
    out.append('  class PG store;')
    for _mod, (eid, label, _desc) in model["externals"].items():
        out.append(f'  {eid}["{label}"]')
        out.append(f"  class {eid} ext;")
    out.append('  BROWSER["Browser / Dashboard"]')
    out.append('  class BROWSER ext;')

    # import edges
    for e in model["edges"]:
        a, b = nodes[e["from"]]["id"], nodes[e["to"]]["id"]
        out.append(f"  {a} --> {b}")

    # annotated edges: db→PG, sources→APIs, server→browser
    if "db" in nodes:
        out.append('  db -.->|psycopg| PG')
    for mod, (eid, _l, _d) in model["externals"].items():
        if mod in nodes:
            out.append(f"  {nodes[mod]['id']} -.->|fetch| {eid}")
    if "viz.server" in nodes:
        out.append('  viz_server -.->|JSON API| BROWSER')
    if "viz.export" in nodes:
        out.append('  viz_export -.->|static snapshot| BROWSER')

    # apply layer classes
    for n in nodes.values():
        out.append(f'  class {n["id"]} {n["layer"]};')
    return "\n".join(out)


def _mermaid_dataflow(model: dict) -> str:
    """A curated left-to-right pipeline: the story the dependency graph implies."""
    return "\n".join([
        "flowchart LR",
        "  classDef ext fill:#e8d8b2,stroke:#8a7647,color:#20150c,stroke-dasharray:4 3;",
        "  classDef store fill:#6b4f8a,stroke:#43305a,color:#fff;",
        "  classDef proc fill:#243b6b,stroke:#152b52,color:#fff;",
        "  classDef out fill:#d2541b,stroke:#8f3710,color:#fff;",
        '  SRC["External feeds<br/>CSV · API · xG · RSS"]:::ext',
        '  ING["sources/*<br/>ingest"]:::proc',
        '  PG[("PostgreSQL<br/>worldcup")]:::store',
        '  TRAIN["models: elo · poisson<br/>draw_model"]:::proc',
        '  PRED["models.predict<br/>ensemble 1X2 + xG"]:::proc',
        '  SIM["models.tournament<br/>Monte Carlo ×50k"]:::proc',
        '  API["viz.server<br/>JSON API"]:::out',
        '  EXP["viz.export<br/>static snapshot"]:::out',
        '  WEB["wcpa26.com<br/>album dashboard"]:::ext',
        "  SRC --> ING --> PG",
        "  PG --> TRAIN --> PRED --> SIM",
        "  PRED --> API",
        "  SIM --> API --> EXP --> WEB",
        "  PG --> API",
    ])


def _module_table(model: dict) -> str:
    rows = ["| Module | Layer | LOC | Deps | Role |", "|---|---|---:|---:|---|"]
    for n in sorted(model["nodes"].values(),
                    key=lambda x: (LAYER_ORDER.index(x["layer"]), x["name"])):
        tag = ("⛁ " if n["db"] else "") + ("🌐 " if n["net"] else "")
        role = (n["role"] or "").replace("|", "\\|")
        rows.append(f"| `{n['name']}` | {n['layer']} | {n['loc']} | "
                    f"{len(n['deps'])} | {tag}{role} |")
    return "\n".join(rows)


def _live_snapshot(model: dict) -> str:
    h, sim = model["health"], model["sim"]
    if not h:
        return "_Database snapshot skipped._"
    if not h.get("connected"):
        return f"> ⚠ Database not reachable ({h.get('error', 'unknown')})."
    lines = ["| Metric | Value |", "|---|---|"]
    for k in ("matches", "finished_matches", "teams", "rated_teams", "news", "predictions"):
        if k in h:
            v = h[k]
            lines.append(f"| {k.replace('_', ' ')} | {v:,} |" if isinstance(v, int)
                         else f"| {k.replace('_', ' ')} | {v} |")
    if h.get("date_range"):
        lines.append(f"| date range | {h['date_range']} |")
    if sim.get("runs"):
        lines.append(f"| last simulation | {sim['runs']:,} runs · leader **{sim.get('leader','?')}** |")
    return "\n".join(lines)


def write_markdown(model: dict, path: str | None = None) -> str:
    path = path or os.path.join(ROOT, "ARCHITECTURE.md")
    t = model["totals"]
    md = f"""<!-- AUTO-GENERATED by `python run.py graph` — do not edit by hand. -->
# WCPA — Backend Architecture (connected graph)

_Generated {model['generated']} · {t['modules']} modules · {t['loc']:,} lines · {t['edges']} import edges._

A pure-stdlib AST scan of the engine. Re-run `python run.py graph` any time the
code changes and this regenerates itself. In VS Code, open the Markdown preview
(`Ctrl+Shift+V`) with the **Markdown Preview Mermaid Support** extension to see
the graphs; for a draggable, zoomable, live version open **`/graph`** on the dev
server (`python run.py viz`) or the exported site.

## Live data snapshot

{_live_snapshot(model)}

## Module dependency graph

Solid arrows are `import` dependencies (A → B means *A imports B*). Dashed arrows
are runtime I/O: the database, external feeds and the browser. `⛁` = touches
PostgreSQL, `🌐` = reaches the network.

```mermaid
{_mermaid_dependency(model)}
```

## Data-flow pipeline

How a result becomes a prediction on the wall — feeds in, album out.

```mermaid
{_mermaid_dataflow(model)}
```

## Modules

{_module_table(model)}

## Live HTTP API ({len(model['endpoints'])} endpoints)

{', '.join(f'`{e}`' for e in model['endpoints']) or '—'}

## CLI commands ({len(model['commands'])})

{', '.join(f'`{c}`' for c in model['commands']) or '—'}
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(md)
    return path


# --------------------------------------------------------------------------- #
# graph_data.js (→ the interactive /graph page)
# --------------------------------------------------------------------------- #
def write_graph_data(model: dict, path: str | None = None) -> str:
    path = path or os.path.join(ROOT, "viz", "static", "graph_data.js")
    # Trim to what the page needs (drop ASTs/source — already not in model).
    payload = {
        "generated": model["generated"],
        "totals": model["totals"],
        "layers": LAYERS, "layerOrder": LAYER_ORDER,
        "nodes": [
            {"id": n["id"], "name": n["name"], "layer": n["layer"],
             "loc": n["loc"], "role": n["role"], "db": n["db"], "net": n["net"],
             "deps": [model["nodes"][d]["id"] for d in n["deps"]],
             "dependents": [model["nodes"][d]["id"] for d in n["dependents"]]}
            for n in model["nodes"].values()
        ],
        "externals": [
            {"id": eid, "label": label, "desc": desc,
             "from": model["nodes"][mod]["id"]}
            for mod, (eid, label, desc) in model["externals"].items()
            if mod in model["nodes"]
        ],
        "endpoints": model["endpoints"], "commands": model["commands"],
    }
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("/* AUTO-GENERATED by `python run.py graph` — do not edit. */\n")
        fh.write("window.WC_GRAPH = ")
        json.dump(payload, fh, ensure_ascii=False, indent=1)
        fh.write(";\n")
    return path


# --------------------------------------------------------------------------- #
# CLI entry (wired into run.py as `python run.py graph`)
# --------------------------------------------------------------------------- #
def main(args: list[str] | None = None) -> None:
    args = args or []
    do_md = "--data" not in args
    do_data = "--md" not in args
    model = build_model(with_health=do_md)

    if do_md:
        p = write_markdown(model)
        print(f"  wrote {os.path.relpath(p, ROOT)}")
    if do_data:
        p = write_graph_data(model)
        print(f"  wrote {os.path.relpath(p, ROOT)}")

    t = model["totals"]
    print(f"\nBackend graph: {t['modules']} modules, {t['loc']:,} LOC, "
          f"{t['edges']} import edges across {len({n['layer'] for n in model['nodes'].values()})} layers.")
    h = model["health"]
    if h.get("connected"):
        print(f"Live DB: {h.get('matches', '?'):,} matches · "
              f"{h.get('rated_teams', '?')} rated teams · {h.get('news', '?')} news.")
    print("Open ARCHITECTURE.md (Mermaid preview) or /graph (interactive) to view.")


if __name__ == "__main__":
    import sys
    main(sys.argv[1:])
