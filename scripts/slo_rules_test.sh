#!/bin/sh
# promtool check + unit tests for deploy/k8s/slo-rules.yaml (needs promtool on PATH; CI uses prom/prometheus).
# The CRD envelope is stripped: `spec:` must be the last top-level key of the rules file.
set -eu
cd "$(dirname "$0")/.."
d=$(mktemp -d)
sed -n '/^spec:/,$p' deploy/k8s/slo-rules.yaml | sed '1d;s/^  //' > "$d/slo-rules.yaml"
cp deploy/k8s/tests/slo-rules.test.yaml "$d/"
promtool check rules "$d/slo-rules.yaml"
promtool test rules "$d/slo-rules.test.yaml"
