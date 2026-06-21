---
name: Schema Additive-Only
description: schema.sql must never drop or rename columns
---
If this PR changes `schema.sql` or `schema_runs.sql`, verify the change is ADDITIVE only:
new tables, new columns, new indexes are fine. FAIL if any column is dropped or renamed,
or if `init` would stop being idempotent / cold-start safe. Suggest an additive migration
instead. Only consider the schema files changed in this PR.
