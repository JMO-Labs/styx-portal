#!/usr/bin/env bash
# CI (issue #18): render templates/rke2-cilium.yaml with Ansible for each encryption type,
# helm template the vendored rke2-cilium chart with its valuesContent, kubeconform all of it.
# Needs ansible (with PyYAML), helm and kubeconform on PATH. Usage: ./validate-cilium.sh [outdir]
set -euo pipefail
cd "$(dirname "$0")"
out="${1:-$(mktemp -d)}"; mkdir -p "$out"
for enc in wireguard ipsec none; do
  ansible localhost -c local -i inventory/hosts.example.yml -m ansible.builtin.template \
    -a "src=templates/rke2-cilium.yaml dest=$out/hcc-$enc.yaml" -e "cilium_encryption_type=$enc" >/dev/null
  python3 -c 'import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))["spec"]["valuesContent"])' \
    "$out/hcc-$enc.yaml" > "$out/values-$enc.yaml"
  # RKE2 injects global.clusterCIDRv4 at install time; 10.42.0.0/16 is its default.
  helm template rke2-cilium charts/rke2-cilium-1.20.400.tgz -n kube-system \
    --set global.clusterCIDRv4=10.42.0.0/16 -f "$out/values-$enc.yaml" > "$out/chart-$enc.yaml"
done
kubeconform -strict -kubernetes-version 1.36.6 -ignore-missing-schemas -summary "$out"/hcc-*.yaml "$out"/chart-*.yaml
