#!/usr/bin/env bash
# Build base + enterprise-netpol overlay and validate offline (vendored Cilium schemas).
# Requires kustomize and kubeconform on PATH (CI installs pinned, sha256-checked builds).
# `--stdin` validates manifests piped on stdin instead of building (used by tests).
set -euo pipefail
cd "$(dirname "$0")/.."
SCHEMAS=deploy/k8s/components/cilium-baseline/schemas
# Third-party kinds with no vendored schema. Unlisted unknown kinds FAIL (no blanket ignore).
SKIP=AlertmanagerConfig,ExternalSecret,PrometheusRule,ServiceMonitor,Cluster,ScheduledBackup,ObjectStore
validate() {
  kubeconform -strict -summary -skip "$SKIP" \
    -schema-location default \
    -schema-location "$SCHEMAS/{{ .ResourceKind }}_{{ .ResourceAPIVersion }}.json"
}
if [ "${1:-}" = "--stdin" ]; then validate; exit; fi
TARGETS=(deploy/k8s deploy/k8s/overlays/enterprise-netpol)
for t in "${TARGETS[@]}"; do
  if [ ! -d "$t" ]; then
    # TODO(styx-portal child ticket adding deploy/k8s/overlays/enterprise-netpol, parent #60):
    # remove this skip once the overlay exists so a missing overlay fails the gate.
    echo "::warning::$t not present yet (policy overlay lands in Children 1-5); skipped" >&2
    continue
  fi
  echo "== $t"
  kustomize build "$t" | validate
done
