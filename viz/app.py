"""
Backwards-compatible entry point.

The dashboard was rebuilt on the standard-library `http.server` (no Flask) to
honour the project's tiny-deps ethos. This shim keeps the old
`python viz/app.py` invocation working — it just launches the new server.

Preferred entry points:
    python run.py viz [port]
    python viz/server.py --port 8008
"""
from __future__ import annotations

from viz.server import serve

if __name__ == "__main__":
    serve()
