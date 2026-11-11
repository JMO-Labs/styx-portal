#!/usr/bin/env bash
# Smoke test: nodes Ready and a pod runs to completion.
set -euo pipefail

kubectl wait --for=condition=Ready nodes --all --timeout=120s
kubectl get nodes -o wide

kubectl run smoke --image=busybox:1.37 --restart=Never --command -- echo hello-from-kind
kubectl wait --for=jsonpath='{.status.phase}'=Succeeded pod/smoke --timeout=180s
kubectl logs smoke
kubectl delete pod smoke --wait=false
echo "smoke OK"
