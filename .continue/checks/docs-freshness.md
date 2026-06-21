---
name: Docs Freshness
description: Keep CLAUDE.md / README in sync with the code
---
If this PR adds, removes, or renames a CLI subcommand in `run.py`, a module under
`models/` or `sources/`, or a top-level file referenced in docs, verify that `CLAUDE.md`
and `README.md` are updated to match. FAIL if a documented command/file no longer exists
or a new one is undocumented (this is the drift that left `.instructions.md` pointing at
deleted files). Make the doc edits if missing. Only consider files changed in this PR.
