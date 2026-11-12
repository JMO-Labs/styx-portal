#!/usr/bin/env bash
# Phase 1 exit evidence: Styx HA demo on kind (design.md §6, #103).
# Deploys CNPG + 3 Styx replicas, checks login + instance list, then kills the
# leader pod and the CNPG primary in turn while polling /api/health.
# Env: MAX_GAP_S (default 30) bound on consecutive non-200 health time.
# Needs: kubectl, helm, docker, kind cluster "spike" (or KIND_CLUSTER).
set -euo pipefail

NS=styx-ha
KIND_CLUSTER=${KIND_CLUSTER:-spike}
MAX_GAP_S=${MAX_GAP_S:-30}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${HA_OUT:-$ROOT/out/ha-demo}
mkdir -p "$OUT"
HEALTH=$OUT/health.log     # "<epoch_ms> <http_code>"
LEADERS=$OUT/leaders.log   # "<epoch> leaders=<n> pod=<name>"
REPORT=$OUT/report.txt
PASS_PW='Ha-Demo-Pass-1234!'
: >"$HEALTH"; : >"$LEADERS"; : >"$REPORT"

say() { echo "$*" | tee -a "$REPORT"; }
k() { kubectl -n "$NS" "$@"; }
bgpids=()
cleanup() { for p in "${bgpids[@]:-}"; do [ -n "$p" ] && kill "$p" 2>/dev/null || true; done; }
trap cleanup EXIT

primary() { k get cluster styx-db -o jsonpath='{.status.currentPrimary}'; }

# Prints "<count> <pod|->" of sessions holding the leader advisory lock (0x5354, 1).
leader_sample() {
  local p out
  p=$(primary 2>/dev/null) || { echo "? -"; return; }
  out=$(k exec "$p" -c postgres -- psql -U postgres -d styx -tAF' ' -c \
    "SELECT host(a.client_addr) FROM pg_locks l JOIN pg_stat_activity a USING (pid)
     WHERE l.locktype='advisory' AND l.granted AND l.classid=21332 AND l.objid=1 AND l.objsubid=2" 2>/dev/null) \
    || { echo "? -"; return; }
  local n=0 ips=() ip
  while read -r ip; do [ -n "$ip" ] && { n=$((n+1)); ips+=("$ip"); }; done <<<"$out"
  local pod=-
  if [ "$n" -ge 1 ]; then
    pod=$(k get pod -l app=styx-backend -o json \
      | jq -r --arg ip "${ips[0]}" '.items[]|select(.status.podIP==$ip)|.metadata.name')
    [ -n "$pod" ] || pod=-
  fi
  echo "$n $pod"
}

wait_one_leader() { # up to ~120 s for exactly one leader; echo its pod
  for _ in $(seq 60); do
    read -r n pod < <(leader_sample)
    if [ "$n" = 1 ] && [ "$pod" != - ]; then echo "$pod"; return 0; fi
    sleep 2
  done
  return 1
}

api() { k exec prober -- curl -s --max-time 5 "$@"; }
login_and_list() {
  local code
  code=$(api -o /dev/null -w '%{http_code}' -c /tmp/jar -X POST http://styx-backend:8000/api/auth/login \
    -H 'content-type: application/json' -d "{\"username\":\"admin\",\"password\":\"$PASS_PW\"}")
  [ "$code" = 200 ] || { say "FAIL: login -> $code"; return 1; }
  code=$(api -o /dev/null -w '%{http_code}' -b /tmp/jar http://styx-backend:8000/api/instances)
  [ "$code" = 200 ] || { say "FAIL: instance list -> $code"; return 1; }
  say "login + instance list OK ($1)"
}
retry() { for _ in $(seq 20); do "$@" && return 0; sleep 3; done; return 1; }

# ---- deploy ----------------------------------------------------------------
helm repo add cnpg https://cloudnative-pg.github.io/charts >/dev/null
helm repo update cnpg >/dev/null
helm upgrade --install cnpg cnpg/cloudnative-pg -n cnpg-system --create-namespace --wait --timeout 5m
kubectl wait --for=condition=Established crd/clusters.postgresql.cnpg.io --timeout=120s

docker build -f "$ROOT/backend/Dockerfile" -t styx-backend:kind "$ROOT"
kind load docker-image styx-backend:kind --name "$KIND_CLUSTER"

kubectl apply -f "$ROOT/test/kind/ha-demo/manifests.yaml"
kubectl -n "$NS" wait --for=condition=Ready cluster/styx-db --timeout=600s
k wait --for=condition=Ready pod/prober --timeout=180s
k rollout status deploy/backend --timeout=600s
k get pods -o wide | tee -a "$REPORT"

# ---- first-run setup + functional checks -----------------------------------
tok=$(k exec "$(primary)" -c postgres -- psql -U postgres -d styx -tAc "SELECT token FROM setup_token WHERE id=1")
[ -n "$tok" ] || { say "FAIL: no setup token"; exit 1; }
code=$(api -o /dev/null -w '%{http_code}' -X POST http://styx-backend:8000/api/auth/setup \
  -H 'content-type: application/json' \
  -d "{\"username\":\"admin\",\"password\":\"$PASS_PW\",\"setup_token\":\"$tok\"}")
[ "$code" = 201 ] || { say "FAIL: setup -> $code"; exit 1; }
login_and_list baseline

leader=$(wait_one_leader) || { say "FAIL: no single leader at start"; exit 1; }
say "initial leader: $leader; primary: $(primary)"

# ---- background samplers ---------------------------------------------------
k exec prober -- sh -c 'while :; do
  c=$(curl -s -o /dev/null -w "%{http_code}" --max-time 1 http://styx-backend:8000/api/health)
  echo "$(date +%s%3N) $c"; sleep 0.2; done' >"$HEALTH" 2>/dev/null &
bgpids+=($!)
( while :; do read -r n pod < <(leader_sample); echo "$(date +%s) leaders=$n pod=$pod" >>"$LEADERS"; sleep 2; done ) &
bgpids+=($!)
sleep 6

# ---- kill the leader pod ---------------------------------------------------
t0=$(date +%s)
say "== killing leader pod $leader"
k delete pod "$leader" --grace-period=0 --force --wait=false
new=""
for _ in $(seq 60); do
  new=$(wait_one_leader || true)
  [ -n "$new" ] && [ "$new" != "$leader" ] && break
  sleep 2
done
[ -n "$new" ] && [ "$new" != "$leader" ] || { say "FAIL: no new leader after pod kill"; exit 1; }
say "new leader: $new after $(( $(date +%s) - t0 )) s"
k rollout status deploy/backend --timeout=300s
retry login_and_list after-leader-kill || exit 1

# ---- kill the CNPG primary -------------------------------------------------
old=$(primary)
t0=$(date +%s)
say "== killing CNPG primary $old"
k delete pod "$old" --grace-period=0 --force --wait=false
for _ in $(seq 90); do
  p=$(primary 2>/dev/null || true)
  [ -n "$p" ] && [ "$p" != "$old" ] && k get pod "$p" -o jsonpath='{.status.containerStatuses[?(@.name=="postgres")].ready}' 2>/dev/null | grep -q true && break
  sleep 2
done
[ "$(primary)" != "$old" ] || { say "FAIL: no CNPG failover"; exit 1; }
say "new primary: $(primary) after $(( $(date +%s) - t0 )) s"
final=$(wait_one_leader) || { say "FAIL: no single leader after failover"; exit 1; }
say "leader after failover: $final"
retry login_and_list after-primary-kill || exit 1
k wait --for=condition=Ready cluster/styx-db --timeout=300s
sleep 10
cleanup; bgpids=()

# ---- assertions ------------------------------------------------------------
say "== leader log: $(wc -l <"$LEADERS") samples"
awk '{split($2,a,"="); if (a[2]=="?") u++; else if (a[2]+0>1) m++; else if (a[2]==0) z++; else o++}
  END{printf "samples: one=%d zero(handover)=%d unknown=%d multiple=%d\n", o,z,u,m}' "$LEADERS" | tee -a "$REPORT"
if grep -Eq 'leaders=([2-9]|[1-9][0-9])' "$LEADERS"; then say "FAIL: more than one leader observed"; exit 1; fi
tail -1 "$LEADERS" | grep -q 'leaders=1 ' || { say "FAIL: last sample not exactly one leader"; exit 1; }

total=$(wc -l <"$HEALTH")
bad=$(awk '$2!="200"' "$HEALTH" | wc -l)
# Longest run of non-200 samples, in ms between the last good sample before and the first good one after.
gap_ms=$(awk '$2!="200"{ if(!s) s=prev; e=$1; run=1; next }
  { if(run){ d=$1-s; if(d>m) m=d; run=0; s=0 } prev=$1 }
  END{ if(run){ d=e-s; if(d>m) m=d } print m+0 }' "$HEALTH")
say "health: $total samples, $bad non-200, longest gap ${gap_ms} ms (bound $((MAX_GAP_S*1000)) ms)"
[ "$total" -gt 50 ] || { say "FAIL: too few health samples"; exit 1; }
[ "$gap_ms" -le $((MAX_GAP_S*1000)) ] || { say "FAIL: health gap over bound"; exit 1; }
say "ha-demo OK"
