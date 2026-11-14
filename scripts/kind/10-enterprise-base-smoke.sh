#!/usr/bin/env bash
# Enterprise base image starts Selkies as non-root under PSA baseline.
set -euo pipefail

IMG=styx-enterprise-base:kind
NS=enterprise-base
POD=enterprise-base

# The Dockerfile default digest is a placeholder; resolve the real one.
DIGEST=$(docker buildx imagetools inspect ubuntu:24.04 --format '{{json .Manifest.Digest}}' | tr -d '"')
echo "ubuntu:24.04 digest: $DIGEST"

docker build --build-arg "UBUNTU_DIGEST=$DIGEST" -f images/enterprise-base/Dockerfile -t "$IMG" .
kind load docker-image "$IMG" --name spike

kubectl apply -f test/kind/enterprise-base-pod.yaml
trap 'kubectl -n "$NS" logs "$POD" --tail=40 || true; kubectl delete ns "$NS" --wait=false || true' EXIT

kubectl -n "$NS" wait --for=condition=Ready "pod/$POD" --timeout=300s

uid=$(kubectl -n "$NS" exec "$POD" -- id -u)
echo "container uid: $uid"
[ "$uid" = "1000" ] || { echo "FAIL: not running as uid 1000"; exit 1; }

kubectl -n "$NS" port-forward "pod/$POD" 18080:8080 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF 2>/dev/null || true; kubectl -n "$NS" logs "$POD" --tail=40 || true; kubectl delete ns "$NS" --wait=false || true' EXIT

code=000
for _ in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18080/ || true)
  [ "$code" = "401" ] && break
  sleep 2
done
echo "gateway HTTP status: $code"
[ "$code" = "401" ] || { echo "FAIL: gateway did not answer 401 (auth required)"; exit 1; }
echo "enterprise-base smoke OK"
