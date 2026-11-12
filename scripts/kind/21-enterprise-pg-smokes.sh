#!/usr/bin/env bash
# styx-portal#6 AC3-AC5 on origin/enterprise: migration smoke, leader smoke, IaC checks.
set -euo pipefail
. test/kind/enterprise-verify/setup.sh
ent_setup
PROBE=$REPO/test/kind/enterprise-verify/leader_probe.py
PRE_EPIC=655c3ed^   # parent of the #21 merge (PR #128)
TAKEOVER_MAX=8      # LEADER_RETRY_S 5 + LEADER_HEARTBEAT_TIMEOUT_S 3; runbook: crash <= 5 s
fail=0
bad() { echo "FAIL: $*"; fail=1; }
cd "$ENT/backend"
PY=.venv/bin/python

echo "== AC3 migration smoke"
work=$(mktemp -d)
for fx in legacy_v1 legacy_v2; do
  db=$work/$fx.db
  $PY -c "import sqlite3,sys; sqlite3.connect(sys.argv[1]).executescript(open(sys.argv[2]).read())" \
    "$db" "tests/fixtures/$fx.sql"
  DATABASE_URL="sqlite+aiosqlite:///$db" $PY -c "import asyncio; from app.database import init_db; asyncio.run(init_db())" \
    || { bad "$fx: app upgrade of pre-Alembic SQLite"; continue; }
  psql_c "DROP DATABASE IF EXISTS mig_$fx WITH (FORCE)" >/dev/null; psql_c "CREATE DATABASE mig_$fx" >/dev/null
  tgt="postgresql+asyncpg://${PG_BASE}/mig_$fx"
  DATABASE_URL=$tgt .venv/bin/alembic upgrade head || { bad "$fx: alembic upgrade head"; continue; }
  rc=0; $PY -m app.tools.sqlite_to_pg --source "$db" --target "$tgt" || rc=$?
  [ "$rc" -eq 0 ] || bad "$fx: copy exit $rc"
  rc=0; out=$($PY -m app.tools.sqlite_to_pg --source "$db" --target "$tgt" --verify-only 2>&1) || rc=$?
  echo "$out"
  { [ "$rc" -eq 0 ] && ! grep -q MISMATCH <<<"$out"; } || bad "$fx: verify exit $rc"
  rc=0; out=$($PY -m app.tools.sqlite_to_pg --source "$db" --target "$tgt" 2>&1) || rc=$?
  { [ "$rc" -eq 2 ] && grep -q 'not empty' <<<"$out"; } && echo "$fx: rerun refused (exit 2, not empty)" \
    || bad "$fx: rerun without --replace exit $rc: $out"
done

echo "== AC4 leader smoke"
psql_c "DROP DATABASE IF EXISTS leader WITH (FORCE)" >/dev/null; psql_c "CREATE DATABASE leader" >/dev/null
export DATABASE_URL="postgresql+asyncpg://${PG_BASE}/leader" PROBE_DIR=$work/probe
mkdir -p "$PROBE_DIR"
start_probe() { $PY "$PROBE" >"$work/probe-$RANDOM.log" 2>&1 & }
leaders() { cat "$PROBE_DIR"/* 2>/dev/null | grep -c 1 || true; }
db_leaders() { psql_c "SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND granted AND classid=21332 AND objid=1 AND objsubid=2"; }
now_ms() { echo $(( $(date +%s%N) / 1000000 )); }
wait_one() {  # $1 timeout s; prints elapsed ms when exactly one leader (probe + pg_locks)
  local t0; t0=$(now_ms)
  while :; do
    [ "$(leaders)" = 1 ] && [ "$(db_leaders)" = 1 ] && { echo $(( $(now_ms) - t0 )); return 0; }
    [ $(( $(now_ms) - t0 )) -gt $(( $1 * 1000 )) ] && return 1
    sleep 0.2
  done
}
max_seen() {  # $1 seconds: sample, print max self-reported leaders
  local m=0 n end=$((SECONDS + $1))
  while [ $SECONDS -lt "$end" ]; do n=$(leaders); [ "$n" -gt "$m" ] && m=$n; sleep 0.2; done
  echo "$m"
}
start_probe; start_probe
wait_one 20 >/dev/null || bad "no single leader after start"
[ "$(max_seen 6)" -le 1 ] || bad "two leaders while idle"
lp=$(grep -l 1 "$PROBE_DIR"/* | head -1); lpid=$(basename "$lp")
echo "leader pid $lpid; kill -9"
kill -9 "$lpid"; rm -f "$lp"
if t=$(wait_one "$TAKEOVER_MAX"); then echo "takeover in ${t} ms (max ${TAKEOVER_MAX}s)"; else bad "no takeover within ${TAKEOVER_MAX}s"; fi
start_probe   # back to two replicas
sleep 3
for i in 1 2 3; do
  echo "postgres restart $i"
  docker restart "$PG_NAME" >/dev/null & rp=$!
  m=$(max_seen 30); wait "$rp" || bad "restart $i: docker restart failed"
  echo "max leaders during/after restart $i: $m"
  [ "$m" -le 1 ] || bad "restart $i: $m leaders at once"
  wait_one 20 >/dev/null || bad "restart $i: no single leader afterwards"
done
pkill -f leader_probe.py || true

echo "== AC5 IaC"
cd "$ENT"
K=5.8.1; KS=029a7f0f4e1932c52a0476cf02a0fd855c0bb85694b82c338fc648dcb53a819d
C=0.7.0; CS=c31518ddd122663b3f3aa874cfe8178cb0988de944f29c74a0b9260920d115d3
curl -sfL -o "$work/k.tgz" "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2Fv$K/kustomize_v${K}_linux_amd64.tar.gz"
echo "$KS  $work/k.tgz" | sha256sum -c -
curl -sfL -o "$work/c.tgz" "https://github.com/yannh/kubeconform/releases/download/v$C/kubeconform-linux-amd64.tar.gz"
echo "$CS  $work/c.tgz" | sha256sum -c -
tar -xzf "$work/k.tgz" -C "$work" kustomize; tar -xzf "$work/c.tgz" -C "$work" kubeconform
if "$work/kustomize" build deploy/enterprise >"$work/ent.yaml"; then
  echo "kustomize build deploy/enterprise: $(grep -c '^kind:' "$work/ent.yaml") objects"
  "$work/kubeconform" -strict -ignore-missing-schemas -summary "$work/ent.yaml" || bad "kubeconform"
else bad "kustomize build deploy/enterprise"; fi
k8s=$(git diff --name-only "$PRE_EPIC" HEAD -- deploy/k8s | grep -v '^deploy/k8s/components/cilium-baseline/' || true)
echo "deploy/k8s changes since $PRE_EPIC outside cilium-baseline (Cilium epic): ${k8s:-none}"
[ -z "$k8s" ] || bad "deploy/k8s changed"
for d in sqlite-to-postgres.md leader-election.md; do
  grep -rqs "$d" zensical.toml docs/enterprise docs/operate || bad "runbook $d not linked"
done
for n in 21 22 23 24; do grep -qE "#$n\b" CHANGELOG.md || bad "CHANGELOG lacks #$n"; done

docker rm -f "$PG_NAME" >/dev/null
[ "$fail" -eq 0 ] && echo "ALL SMOKES OK"
exit "$fail"
