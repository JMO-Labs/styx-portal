#!/usr/bin/env bash
# Kyverno admits only cosign-signed, digest-pinned images from the allowlisted registry
# in desktop namespaces (deploy/enterprise/kyverno). Registry is in-cluster over plain HTTP.
set -euo pipefail

KYVERNO_CHART=3.5.2
COSIGN_VERSION=v2.5.3
REG=registry.registry.svc.cluster.local:5000
WORK=$(mktemp -d)
trap 'kill ${PF_PID:-0} 2>/dev/null || true; rm -rf "$WORK"' EXIT

echo "== cosign $COSIGN_VERSION"
curl -fsSL -o "$WORK/cosign" \
  "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64"
chmod +x "$WORK/cosign"
export COSIGN_PASSWORD=""
(cd "$WORK" && ./cosign generate-key-pair >/dev/null)

echo "== registry"
kubectl apply -f test/kind/kyverno-registry.yaml
kubectl -n registry rollout status deploy/registry --timeout=180s
kubectl -n registry port-forward svc/registry 5000:5000 >/dev/null 2>&1 &
PF_PID=$!
for _ in $(seq 30); do curl -fs localhost:5000/v2/ >/dev/null && break; sleep 1; done

echo "== images"
push() { # <src> <repo:tag> -> prints digest
  docker pull -q "$1" >/dev/null
  docker tag "$1" "localhost:5000/$2"
  docker push "localhost:5000/$2" | awk '/digest:/ {print $3}'
}
SIGNED=$(push busybox:1.37 styx/signed:1)
UNSIGNED=$(push busybox:1.36 styx/unsigned:1)
"$WORK/cosign" sign --yes --key "$WORK/cosign.key" --tlog-upload=false \
  --allow-insecure-registry "localhost:5000/styx/signed@$SIGNED"

echo "== kyverno $KYVERNO_CHART"
helm repo add kyverno https://kyverno.github.io/kyverno/ >/dev/null
helm repo update >/dev/null
helm install kyverno kyverno/kyverno --version "$KYVERNO_CHART" -n kyverno --create-namespace \
  --set admissionController.container.extraArgs.allowInsecureRegistry=true \
  --set admissionController.replicas=1 \
  --set backgroundController.enabled=false --set cleanupController.enabled=false \
  --set reportsController.enabled=false --wait --timeout 10m

echo "== policy"
sed '1d;$d' "$WORK/cosign.pub" | sed 's/^/                      /' > "$WORK/key.txt"
sed -e "s#harbor.example.internal#$REG#g" \
  -e "/REPLACE_WITH_COSIGN_PUBLIC_KEY/{r $WORK/key.txt" -e 'd}' \
  deploy/enterprise/kyverno/clusterpolicy.yaml > "$WORK/policy.yaml"
kubectl apply -f "$WORK/policy.yaml"
kubectl wait --for=condition=Ready clusterpolicy/styx-signed-images --timeout=120s

kubectl create namespace desktop-test
kubectl label namespace desktop-test styx.io/desktop=true

try() { # <name> <image>: server-side dry-run so admission runs but nothing is pulled
  kubectl -n desktop-test run "$1" --image="$2" --restart=Never --dry-run=server -o name 2>&1
}
# Kyverno webhooks can lag behind policy readiness; retry the positive case.
ok=0
for _ in $(seq 12); do
  if out=$(try good "$REG/styx/signed@$SIGNED"); then ok=1; break; fi
  echo "$out"; sleep 5
done
[ "$ok" = 1 ] || { echo "FAIL: signed allowlisted pod rejected"; exit 1; }
echo "PASS: signed allowlisted admitted"

if out=$(try unsigned "$REG/styx/unsigned@$UNSIGNED"); then
  echo "FAIL: unsigned admitted"; exit 1
fi
echo "$out"; echo "PASS: unsigned rejected"

if out=$(try foreign "docker.io/library/busybox@$SIGNED"); then
  echo "FAIL: non-allowlisted registry admitted"; exit 1
fi
echo "$out"; echo "PASS: non-allowlisted rejected"

if out=$(try tag "$REG/styx/signed:1"); then
  echo "FAIL: tag-only reference admitted"; exit 1
fi
echo "$out"; echo "PASS: tag without digest rejected"
echo "kyverno OK"
