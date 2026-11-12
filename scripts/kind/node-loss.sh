#!/usr/bin/env bash
# Spike: non-graceful node shutdown. Stop a worker, taint it out-of-service,
# and check the Deployment pod is rescheduled to another node (ADR-0054).
set -euo pipefail

NS=node-loss
trap 'kubectl delete ns "$NS" --wait=false >/dev/null 2>&1 || true' EXIT

kubectl wait --for=condition=Ready nodes --all --timeout=180s
kubectl create ns "$NS"
kubectl -n "$NS" apply -f - <<'Y'
apiVersion: apps/v1
kind: Deployment
metadata: {name: home}
spec:
  replicas: 1
  selector: {matchLabels: {app: home}}
  template:
    metadata: {labels: {app: home}}
    spec:
      containers:
        - name: c
          image: busybox:1.37
          command: [sleep, "3600"]
          volumeMounts: [{name: home, mountPath: /home/user}]
      volumes:
        - name: home
          emptyDir: {}
Y
kubectl -n "$NS" rollout status deploy/home --timeout=180s

victim=$(kubectl -n "$NS" get pod -l app=home -o jsonpath='{.items[0].spec.nodeName}')
echo "victim node: $victim"
docker stop "$victim"

echo "waiting for $victim NotReady"
for _ in $(seq 60); do
  st=$(kubectl get node "$victim" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')
  [ "$st" != "True" ] && break
  sleep 5
done
[ "$st" != "True" ] || { echo "FAIL: $victim still Ready"; exit 1; }

# Refuses Ready nodes
other=$(kubectl get nodes -o name | sed 's|node/||' | grep -v -e "$victim" -e control-plane | head -1)
if scripts/node-out-of-service.sh --yes "$other"; then
  echo "FAIL: script accepted Ready node $other"; exit 1
fi

scripts/node-out-of-service.sh --yes "$victim"

echo "waiting for pod on another node"
for _ in $(seq 60); do
  new=$(kubectl -n "$NS" get pod -l app=home --field-selector=status.phase=Running \
    -o jsonpath='{range .items[?(@.metadata.deletionTimestamp==null)]}{.spec.nodeName}{"\n"}{end}' | head -1)
  [ -n "$new" ] && [ "$new" != "$victim" ] && break
  new=""
  sleep 5
done
[ -n "$new" ] || { echo "FAIL: pod not rescheduled"; kubectl -n "$NS" get pod -o wide; exit 1; }
echo "rescheduled to $new"

scripts/node-out-of-service.sh --clear "$victim"
kubectl get node "$victim" -o jsonpath='{.spec.taints}' | grep -q out-of-service && { echo "FAIL: taint remains"; exit 1; }
docker start "$victim" >/dev/null
echo "node-loss OK"
