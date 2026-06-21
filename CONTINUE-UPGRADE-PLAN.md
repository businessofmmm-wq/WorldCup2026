# WCPA26 ← Continue: Practices Benchmark & Upgrade Plan

**Date:** 2026-06-21
**Reference:** [continuedev/continue](https://github.com/continuedev/continue) @ `main` (~33.2k★, Apache-2.0)
**Scope:** Compare Continue's repo/dev-tooling practices against WorldCup2026 and propose
upgrades. **No code changed** — this is the plan. Every upgrade below ships as a
paste-ready artifact; say the word and I'll apply the ones you pick.

---

## What Continue actually does (the transferable parts)

Continue is a TypeScript monorepo, so most of its surface (eslint/prettier, husky,
JetBrains/VSCode release pipelines) is language-specific noise for a pure-Python engine.
After filtering, four patterns are genuinely worth porting:

1. **AI checks in CI** — `.continue/checks/*.md`. Each check is a tiny markdown file
   (`name` + `description` frontmatter + a prompt) that runs as a **GitHub status check**
   on every PR via the open-source `cn` CLI: green if the code looks good, red with a
   suggested diff if not. Continue ships checks like `security-audit.md`, `setup-scripts.md`
   (keep install scripts in sync), `stale-comments.md`, `update-agents-md.md`. Example:
   ```markdown
   ---
   name: Security Audit
   description: Security Audit
   ---
   Please audit this pull request for any security vulnerabilities that were introduced…
   When you are done, please make the required changes.
   ```
2. **Versioned agent rules** — `.continue/rules/*.md` (e.g. `programming-principles.md`,
   `no-any-types.md`, `unit-testing-rules.md`). Persistent, source-controlled coding
   constraints that any agent reads — the same job your `CLAUDE.md` does, but split into
   small composable files and tool-agnostic.
3. **A self-updating context file** — Continue keeps an `AGENTS.md` and has an
   `update-agents-md` check that forces it to stay current on every PR. (Your project's
   pain point exactly: `.instructions.md` had drifted to reference files that no longer exist.)
4. **Pre-commit enforcement** — Continue uses husky so checks run before code lands. Your
   equivalent gate (`run.py audit`) exists but is only invoked manually.

Lower-value-for-solo extras (noted, not recommended now): agentic PR bots
(`auto-fix-failed-tests.yml`, `similar-issues.yml`, `tidy-up-codebase.yml`,
`snyk-agent.yaml`), Dependabot/dependency-graph submission, CONTRIBUTING/CODE_OF_CONDUCT/CLA.

---

## Benchmark: Continue vs WCPA26

| Practice | Continue | WCPA26 today | Gap |
|---|---|---|---|
| Agent context file | `AGENTS.md`, kept fresh by a check | `CLAUDE.md` (just added) + stale `.instructions.md` | Consolidate + keep fresh |
| Versioned rules | `.continue/rules/*.md` (25 files) | All prose inside `CLAUDE.md` | Optional split |
| Deterministic CI gate | eslint/prettier/tsc + tests | `run.py audit` (strong: secrets, SQL, headers, load) | ✅ already good |
| AI judgment gate on changes | `.continue/checks/*.md` on every PR | none | **Main opportunity** |
| Pre-commit hook | husky | none | Cheap, high value |
| Branch/PR discipline | PRs + status checks | direct `git push origin master` (`publish.bat`) | Blocks #checks until addressed |
| Toolchain pin | `.node-version` / `.nvmrc` | "Python 3.12+" in prose only | Add `.python-version` |
| Dev formatter/linter | prettier + shared eslint | none | Optional `ruff` (dev-only) |
| Dependency security | Snyk + dep-graph workflows | tiny pinned deps + audit | Optional Dependabot |

Bottom line: your **deterministic** gate is already better than most repos. What you're
missing is the **AI-judgment** layer Continue pioneered — and the plumbing (a PR flow) to
hang it on.

---

## Upgrade plan (prioritized)

### 1 — [HIGH] Add a pre-commit gate (no PR flow required)
The cheapest win and it fits your direct-push workflow as-is. A git pre-commit hook that
runs your existing audit + a byte-compile so a broken or secret-leaking commit never lands.

`.githooks/pre-commit`:
```bash
#!/usr/bin/env bash
set -e
echo "[pre-commit] compile check…"
python -m compileall -q run.py config.py db.py models sources tools viz
echo "[pre-commit] audit (secrets/SQL/headers)…"
python run.py audit
```
Activate (one time): `git config core.hooksPath .githooks && chmod +x .githooks/pre-commit`.
Effort: ~5 min. No new dependencies.

### 2 — [HIGH] Adopt `.continue/checks/` tailored to WCPA's real invariants
Port Continue's pattern, but write checks around *your* constraints, not React/TS ones. I'd
ship five, each a small markdown file under `.continue/checks/`:

- **tiny-deps-guard** — fail if a diff adds `numpy`/`scipy`/`pandas` or a web framework
  (your #1 stated constraint).
- **schema-additive** — fail if `schema.sql` drops or renames a column (must be additive-only).
- **secret-scan** — no credentials in source; everything via `.env`/env.
- **backtest-leakage** — when `models/` or tuning changes, confirm the change is scored on
  held-out data and RPS didn't regress (mirrors your `/backtest-tune` skill's gate).
- **docs-freshness** — when CLI commands or files move, update `CLAUDE.md`/`README`
  (this is the check that would have caught your stale `.instructions.md`).

Example (`.continue/checks/tiny-deps-guard.md`):
```markdown
---
name: Tiny Deps Guard
description: Block heavyweight or framework dependencies
---
Review this PR's diff to requirements.txt and any imports. FAIL if it adds numpy, scipy,
pandas, or any web framework (flask, django, fastapi). The engine is deliberately pure
Python on the stdlib + requests + psycopg. If a new dependency appears, explain why and
suggest a stdlib alternative. Only consider files changed in this PR.
```
**Caveat:** checks run via the `cn` CLI and need (a) a PR to attach to and (b) a model/API
key in CI. See #3 and #4. Effort to author the five checks: ~30 min.

### 3 — [MEDIUM] Introduce a lightweight PR flow so checks have something to gate
Today `publish.bat` does `git push origin master` directly, so there's no PR for an AI check
(or any reviewer) to inspect. Minimal change: develop on a `work` branch, open a PR to
`master`, let checks run, then merge. Your existing deploy automation can stay pinned to
`master` unchanged. Without this, #2 has nothing to attach to. Effort: a habit change, not code.

### 4 — [MEDIUM] Wire the checks into GitHub Actions
A single workflow runs the Continue CLI over changed files on each PR (parallels Continue's
own `pr-checks.yaml`). Sketch:
```yaml
name: ai-checks
on: pull_request
jobs:
  continue:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm i -g @continuedev/cli
      - run: cn --check .continue/checks   # needs a model key in repo secrets
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```
**Honest trade-off:** this adds an external LLM dependency and a per-PR cost to a project
whose whole ethos is tiny-and-self-contained. Your deterministic `run.py audit` already
covers secrets/SQL/headers for free. I'd treat the AI checks as a *complement* for the
judgment-y stuff (leakage, doc drift, dep creep) — not a replacement.

### 5 — [LOW] Toolchain + hygiene niceties
- `.python-version` containing `3.12` (pyenv/CI pin — Continue's `.nvmrc` analog).
- Optional dev-only `ruff` config for lint/format (never shipped at runtime, so it respects
  the tiny-deps rule). Add `ruff` to a `requirements-dev.txt`, not `requirements.txt`.
- Optionally migrate `CLAUDE.md`'s hard constraints into 3–4 `.continue/rules/*.md` files so
  Continue/Cursor/other agents read the same rules — or symlink `AGENTS.md → CLAUDE.md` to
  satisfy the broader `AGENTS.md` convention with zero duplication.

---

## Recommendation

Do **#1 now** (pure win, no strings). Author the **#2** checks since they encode invariants
you already care about. Treat **#3/#4** as a deliberate choice: adopt them only if you want
agentic review and are OK adding an LLM call to CI — otherwise keep them as drafts and let
`run.py audit` + the pre-commit hook be your gate. **#5** is polish.

Say which numbers you want and I'll generate the exact files (checks, hook, workflow,
`.python-version`) on a branch for review — still no direct edits to `master`.

---
_Sources: continuedev/continue — repo root, `.continue/checks/`, `.continue/rules/`,
`.github/workflows/` (GitHub API + raw, fetched 2026-06-21)._
