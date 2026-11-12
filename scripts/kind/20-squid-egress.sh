#!/usr/bin/env bash
# Desktop egress works only via Squid; category blocking applies (ADR-0040).
# Installs Cilium over kindnet, applies cilium-baseline + deploy/enterprise/squid
# (test category list: pastebin.com), then curls from a desktop-labelled pod.
set -euo pipefail

CILIUM_VERSION=1.20.4
OVERLAY=test/kind/squid-egress
# Trailing dot = absolute name. With ndots:5 musl (curl image) tries the search
# list first; the node's host search domain is outside **.cluster.local, Cilium
# answers REFUSED and musl aborts instead of falling through to the real name.
PROXY=http://squid.egress-proxy.svc.cluster.local.:3128
FAILED=0

check() { # <name> <expected: ok|squid-deny|drop> <curl args...>
  local name=$1 want=$2 out err rc code connect; shift 2
  set +e
  out=$(kubectl -n styx-instances exec desktop-test -- \
    curl -sS -o /dev/null -m 15 -w '%{http_code} %{http_connect}' "$@" 2>/tmp/check.err)
  rc=$?
  set -e
  err=$(tr '\n' ' ' </tmp/check.err)
  read -r code connect <<<"$out" || true
  case "$want" in
    ok) [ $rc -eq 0 ] && [[ "$code" =~ ^[23] ]] ;;
    # Squid ACL deny: CONNECT answered 403 (curl rc 56) or plain 403.
    squid-deny) [ "$connect" = 403 ] || [ "$code" = 403 ] ;;
    # Cilium: DNS refused (6), connect refused/dropped (7) or timeout (28).
    drop) [[ " 6 7 28 " == *" $rc "* ]] ;;
  esac && echo "PASS: $name (rc=$rc, http=$code connect=$connect $err)" && return
  echo "FAIL: $name (want $want; rc=$rc, http=$code connect=$connect $err)"; FAILED=1
}

echo "== cilium $CILIUM_VERSION"
helm repo add cilium https://helm.cilium.io >/dev/null
helm upgrade --install cilium cilium/cilium --version "$CILIUM_VERSION" -n kube-system \
  --set ipam.mode=kubernetes --set cni.exclusive=true --set operator.replicas=1 \
  --set kubeProxyReplacement=false --set image.pullPolicy=IfNotPresent \
  --wait --timeout 10m
kubectl -n kube-system rollout status ds/cilium --timeout=300s
# Pods created under kindnet must be re-created to join Cilium.
kubectl -n kube-system rollout restart deploy/coredns
kubectl -n kube-system rollout status deploy/coredns --timeout=180s

echo "== apply baseline + squid"
kubectl kustomize "$OVERLAY" > /tmp/squid-egress.yaml
kubectl apply -f /tmp/squid-egress.yaml
kubectl -n egress-proxy rollout status deploy/squid --timeout=300s

echo "== test pod (labelled as a desktop)"
kubectl -n styx-instances run desktop-test --image=curlimages/curl:8.11.1 \
  --labels=app.kubernetes.io/name=desktop-test --restart=Never \
  --overrides='{"spec":{"securityContext":{"runAsNonRoot":true,"runAsUser":1000,"seccompProfile":{"type":"RuntimeDefault"}},"containers":[{"name":"desktop-test","image":"curlimages/curl:8.11.1","command":["sleep","3600"],"securityContext":{"allowPrivilegeEscalation":false,"capabilities":{"drop":["ALL"]}}}]}}'
kubectl -n styx-instances wait --for=condition=Ready pod/desktop-test --timeout=180s
kubectl -n styx-instances exec desktop-test -- cat /etc/resolv.conf
sleep 10 # policy propagation

echo "== checks"
check "via squid: https://example.com allowed" ok -x "$PROXY" https://example.com
check "via squid: https://pastebin.com blocked by category" squid-deny -x "$PROXY" https://pastebin.com
check "direct: https://example.com dropped by cilium" drop https://example.com

if [ $FAILED -ne 0 ]; then
  echo "FAIL: squid egress spike"
  kubectl -n egress-proxy logs deploy/squid -c squid --tail=30 || true
  exit 1
fi
echo "PASS: squid egress spike"
