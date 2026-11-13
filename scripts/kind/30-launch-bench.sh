#!/usr/bin/env bash
# Desktop-like pod launch benchmark: create->Ready seconds, p50/p95 (nearest rank).
# Fails if p95 >= LIMIT_P95 seconds.
set -euo pipefail

DIR="test/kind/launch-bench"
N="${LAUNCH_BENCH_PODS:-20}"
LIMIT_P95="${LAUNCH_BENCH_LIMIT_P95:-10}"
NS=launch-bench

# percentile <p> <sorted values...> : nearest-rank
percentile() {
  local p=$1; shift
  local n=$# rank
  rank=$(awk -v p="$p" -v n="$n" 'BEGIN{r=p*n/100; i=int(r); if(r>i)i++; if(i<1)i=1; print i}')
  local arr=("$@")
  echo "${arr[$((rank-1))]}"
}

# Retry transient admission-webhook failures (kyverno closes idle connections).
retry() {
  local a
  for a in 1 2 3 4 5; do
    "$@" && return 0
    echo "retry $a: $*" >&2
    sleep 5
  done
  return 1
}

retry kubectl apply -f "$DIR/namespace.yaml" >&2
retry kubectl apply -f "$DIR/prepull-daemonset.yaml" >&2
kubectl -n "$NS" rollout status ds/prepull --timeout=300s >&2

times=()
for i in $(seq 1 "$N"); do
  name="bench-$i"
  start=$(date +%s.%N)
  retry kubectl apply -f <(sed "s/__NAME__/$name/g" "$DIR/pod.yaml") >&2
  kubectl -n "$NS" wait --for=condition=Ready "pod/$name" --timeout=120s >&2
  end=$(date +%s.%N)
  t=$(awk -v s="$start" -v e="$end" 'BEGIN{printf "%.3f", e-s}')
  echo "pod $name create->Ready ${t}s" >&2
  times+=("$t")
  retry kubectl delete -f <(sed "s/__NAME__/$name/g" "$DIR/pod.yaml") \
    --ignore-not-found --wait=true --timeout=120s >&2
done

retry kubectl delete -f "$DIR/prepull-daemonset.yaml" --ignore-not-found --wait=false >&2 || true

mapfile -t sorted < <(printf '%s\n' "${times[@]}" | sort -n)
p50=$(percentile 50 "${sorted[@]}")
p95=$(percentile 95 "${sorted[@]}")

echo "LAUNCH_P50_SECONDS=$p50"
echo "LAUNCH_P95_SECONDS=$p95"
printf '%s\n' "${times[@]}" | jq -sc --argjson p50 "$p50" --argjson p95 "$p95" \
  '{pods: length, p50_seconds: $p50, p95_seconds: $p95, samples: .}' | tee launch-bench.json

if awk -v p="$p95" -v l="$LIMIT_P95" 'BEGIN{exit !(p>=l)}'; then
  echo "FAIL: p95 ${p95}s >= ${LIMIT_P95}s" >&2
  exit 1
fi
