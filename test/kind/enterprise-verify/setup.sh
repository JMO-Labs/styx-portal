# shellcheck shell=bash
# Shared setup for the styx-portal#6 enterprise integration spikes (sourced).
# Checks out origin/enterprise into a worktree, starts postgres:17 in Docker,
# builds the backend venv from uv.lock (same steps as .github/actions/setup-backend).
set -euo pipefail

REPO=$(pwd)
ENT=${ENT_DIR:-/tmp/styx-enterprise}
PG_NAME=styx-verify-pg
PG_PORT=55432
PG_PASS=styx-verify
PG_BASE="styx:${PG_PASS}@127.0.0.1:${PG_PORT}"
export PGPASSWORD=$PG_PASS

ent_checkout() {
  git -C "$REPO" fetch -q origin enterprise
  [ -d "$ENT" ] || git -C "$REPO" worktree add -q --detach "$ENT" FETCH_HEAD
  echo "enterprise HEAD: $(git -C "$ENT" log -1 --format='%h %s')"
}

pg_up() {
  docker rm -f "$PG_NAME" >/dev/null 2>&1 || true
  docker run -d --name "$PG_NAME" -p "${PG_PORT}:5432" -e POSTGRES_USER=styx \
    -e POSTGRES_PASSWORD="$PG_PASS" -e POSTGRES_DB=styx_test postgres:17 >/dev/null
  pg_wait
}

pg_wait() {
  for _ in $(seq 60); do
    docker exec "$PG_NAME" pg_isready -U styx -d styx_test -h 127.0.0.1 >/dev/null 2>&1 && return 0
    sleep 1
  done
  echo "postgres not ready"; return 1
}

psql_c() { docker exec -e PGPASSWORD="$PG_PASS" "$PG_NAME" psql -U styx -h 127.0.0.1 -d "${2:-styx_test}" -tAc "$1"; }

venv_up() {
  [ -x "$ENT/backend/.venv/bin/python" ] && return 0
  ( cd "$ENT/backend"
    python3 -m venv .venv
    .venv/bin/pip install -q --upgrade pip
    .venv/bin/pip install -q uv==0.13.7
    .venv/bin/python -m uv export --frozen --extra dev --no-emit-project -q -o .venv/requirements.lock.txt
    .venv/bin/pip install -q --require-hashes -r .venv/requirements.lock.txt
    .venv/bin/pip install -q --no-deps -e . )
}

ent_setup() { ent_checkout; pg_up; venv_up; }
