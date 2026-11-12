#!/usr/bin/env bash
# Mark a dead node out-of-service so pods/volumes fail over (non-graceful node shutdown).
# Usage: node-out-of-service.sh [--yes] [--clear] <node>
set -euo pipefail

TAINT_KEY="node.kubernetes.io/out-of-service"
TAINT="${TAINT_KEY}=nodeshutdown:NoExecute"
yes=0 clear=0 node=""

usage() { echo "usage: $0 [--yes] [--clear] <node>" >&2; exit 2; }

for a in "$@"; do
  case "$a" in
    --yes|-y) yes=1 ;;
    --clear) clear=1 ;;
    -h|--help) usage ;;
    -*) usage ;;
    *) [ -z "$node" ] || usage; node="$a" ;;
  esac
done
[ -n "$node" ] || usage

ready=$(kubectl get node "$node" -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}')

if [ "$clear" = 1 ]; then
  kubectl taint node "$node" "${TAINT_KEY}:NoExecute-" || true
  echo "cleared out-of-service taint on $node"
  exit 0
fi

if [ "$ready" = "True" ]; then
  echo "refusing: node $node is Ready; the taint is only for nodes that are down" >&2
  exit 1
fi

if [ "$yes" != 1 ]; then
  echo "Node $node is NotReady (Ready=$ready). Tainting forces its pods to be deleted and volumes detached."
  echo "Only continue if the node is confirmed powered off or isolated (split-brain risk)."
  read -r -p "Apply $TAINT to $node? [y/N] " ans
  case "$ans" in y|Y|yes|YES) ;; *) echo "aborted"; exit 1 ;; esac
fi

kubectl taint node "$node" "$TAINT" --overwrite
echo "tainted $node"
