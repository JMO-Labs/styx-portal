#!/usr/bin/env bash
# 3-session load-harness smoke: soak.py (fleet + http probe + D47 gate) against a fake portal in kind.
set -euo pipefail

PORT=18000
N=3
SOAK_DIR=e2e/stream-ab
WORK=$(mktemp -d)
HOSTS_ADDED=""
PF_PID=""

cleanup() {
  [ -n "$PF_PID" ] && kill "$PF_PID" 2>/dev/null || true
  if [ -n "$HOSTS_ADDED" ]; then sudo sed -i '/# loadtest-smoke$/d' /etc/hosts || true; fi
  kubectl delete -f test/kind/fake-portal.yaml --ignore-not-found --wait=false || true
  kubectl delete configmap fake-portal-src --ignore-not-found || true
  rm -rf "$WORK"
}
trap cleanup EXIT

kubectl create configmap fake-portal-src --from-file=fake-portal.py=test/kind/fake-portal.py
kubectl apply -f test/kind/fake-portal.yaml
kubectl rollout status deployment/fake-portal --timeout=300s

kubectl port-forward svc/fake-portal "$PORT:8000" >"$WORK/pf.log" 2>&1 &
PF_PID=$!
for _ in $(seq 1 30); do
  curl -fsS "http://localhost:$PORT/" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://localhost:$PORT/" >/dev/null

# soak_fleet probes http://<session>.<portal host>/: map the session names to loopback.
for i in $(seq 0 $((N - 1))); do
  echo "127.0.0.1 fleet-$i.localhost # loadtest-smoke"
done | sudo tee -a /etc/hosts >/dev/null
HOSTS_ADDED=1

python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install -q requests

rm -rf "$SOAK_DIR/results"
STYX_USER=smoke STYX_PASS=smoke "$WORK/venv/bin/python" "$SOAK_DIR/soak.py" \
  --sessions "$N" --minutes 1 --probe http --portal "http://localhost:$PORT" || echo "soak.py exited non-zero"

REPORT_JSON=$(ls -t "$SOAK_DIR"/results/gate-*.json 2>/dev/null | head -1 || true)
[ -n "$REPORT_JSON" ] || { echo "FAIL: report JSON missing"; exit 1; }
REPORT_MD="${REPORT_JSON%.json}.md"
[ -f "$REPORT_MD" ] && cat "$REPORT_MD"
jq -e '.verdict == "pass"' "$REPORT_JSON" >/dev/null || { echo "FAIL: verdict is not pass"; jq . "$REPORT_JSON"; exit 1; }
echo "loadtest smoke OK"
