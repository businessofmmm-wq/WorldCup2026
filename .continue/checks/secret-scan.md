---
name: Secret Scan
description: No credentials in source
---
Audit this PR's diff for hardcoded secrets: database URLs with passwords, API tokens
(Cloudflare, football-data, SportsDB, balldontlie), private keys. Credentials must come
from the environment / a gitignored `.env` via `config.py`'s loader — never baked into
source. FAIL with the offending file and line if a live-looking secret is introduced, and
suggest moving it to `.env` + `.env.example`. Only consider files changed in this PR.
