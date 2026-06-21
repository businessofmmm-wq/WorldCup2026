#!/usr/bin/env bash
# Pre-flight gate for the deploy skill. Exits non-zero on the first failed check
# so the pipeline never starts from a broken state. Run from the project root.
set -uo pipefail
fail=0

check() { # name, test-command
  if eval "$2" >/dev/null 2>&1; then
    echo "  PASS  $1"
  else
    echo "  FAIL  $1"
    fail=1
  fi
}

echo "WCPA deploy pre-flight:"
check ".env present"            "test -f .env"
check "wrangler.toml present"   "test -f wrangler.toml"
check "run.py present"          "test -f run.py"
check "dist/ writable"          "mkdir -p dist && test -w dist"
check "Postgres reachable"      "python run.py health"

if [ "$fail" -ne 0 ]; then
  echo "Pre-flight FAILED — do not deploy."
  exit 1
fi
echo "Pre-flight OK."
