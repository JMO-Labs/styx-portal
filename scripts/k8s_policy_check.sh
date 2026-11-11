#!/usr/bin/env bash
# Build base + enterprise-netpol overlay and validate offline (vendored Cilium schemas).
# Requires kustomize and kubeconform on PATH (CI installs pinned, sha256-checked builds).
set -euo pipefail
cd "$(dirname "$0")/.."
SCHEMAS=deploy/k8s/components/cilium-baseline/schemas
TARGETS=(deploy/k8s deploy/k8s/overlays/enterprise-netpol)
for t in "${TARGETS[@]}"; do
  if [ ! -d "$t" ]; then
    echo "::warning::$t not present yet (policy overlay lands in Children 1-5); skipped" >&2
    continue
  fi
  echo "== $t"
  kustomize build "$t" | kubeconform -strict -summary \
    -schema-location default \
    -schema-location "$SCHEMAS/{{ lower .ResourceKind }}_{{ .ResourceAPIVersion }}.json"
done
