#!/usr/bin/env bash
# Trivy license scans for the component register (issue #17). Same flags locally and in CI.
# Usage: scripts/license_scan.sh [trivy-binary]   (run from the repo root, after the backend
# venv is built from backend/uv.lock). Writes repo.cdx.json and venv.cdx.json.
set -euo pipefail
TRIVY="${1:-trivy}"
"$TRIVY" fs -q --scanners license --include-dev-deps --format cyclonedx -o repo.cdx.json \
  --skip-dirs backend/.venv --skip-dirs '**/node_modules' --skip-dirs .cache \
  --skip-dirs .trivy-bin --skip-dirs .k8stools --skip-dirs .openbao-bin .
# pip itself is skipped: its version depends on the runner, not on uv.lock.
"$TRIVY" rootfs -q --scanners license --format cyclonedx -o venv.cdx.json \
  --skip-dirs 'lib/python3.*/site-packages/pip' \
  --skip-files 'lib/python3.*/site-packages/pip-*.dist-info/METADATA' backend/.venv
