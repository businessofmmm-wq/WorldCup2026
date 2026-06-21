---
name: Tiny Deps Guard
description: Block heavyweight or framework dependencies
---
Review this PR's diff to `requirements.txt` and any new imports. FAIL if it adds
`numpy`, `scipy`, `pandas`, or any web framework (`flask`, `django`, `fastapi`,
`starlette`). The engine is deliberately pure Python on the standard library plus
`requests` and `psycopg` (with `Pillow` build-time only). If a new runtime dependency
appears, explain why and suggest a stdlib alternative. Only consider files changed in
this PR.
