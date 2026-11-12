#!/usr/bin/env bash
# styx-portal#6 AC2: backend suite on origin/enterprise, on SQLite and on Postgres 17.
# Lists every skip whose reason is dialect-only ("... test on postgres|sqlite").
set -euo pipefail
. test/kind/enterprise-verify/setup.sh
ent_setup
cd "$ENT/backend"

run_suite() {  # $1 label; env passed by caller
  local log=/tmp/pytest-$1.log rc=0
  .venv/bin/python -m pytest -q -rs -p no:cacheprovider >"$log" 2>&1 || rc=$?
  tail -n 5 "$log"
  echo "== dialect-only skips ($1): $(grep -cE 'SKIPPED.*test on (postgres|sqlite)' "$log" || true)"
  grep -E 'SKIPPED.*test on (postgres|sqlite)' "$log" | head -n 40 || true
  [ "$rc" -eq 0 ] || { grep -E '^(FAILED|ERROR)' "$log" | head -n 40; echo "FAIL suite $1 rc=$rc"; }
  return "$rc"
}

rc=0
echo "== suite: sqlite"
run_suite sqlite || rc=1
echo "== suite: postgres 17"
STYX_TEST_DATABASE_URL="postgresql+asyncpg://${PG_BASE}/styx_test" \
TEST_PG_URL="postgresql://${PG_BASE}/styx_test" run_suite postgres || rc=1
docker rm -f "$PG_NAME" >/dev/null
exit "$rc"
