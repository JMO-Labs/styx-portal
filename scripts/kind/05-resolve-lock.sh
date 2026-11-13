#!/usr/bin/env bash
# Resolve phase1.images to digests in CI and print the full lock between markers so it can be
# committed as deploy/enterprise/images/phase1.lock (the agent sandbox has no registry access).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
command -v skopeo >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq skopeo; }
scripts/resolve_phase1_digests.sh out-phase1.lock >/dev/null
echo "==== BEGIN phase1.lock ===="
cat out-phase1.lock
echo "==== END phase1.lock ===="
rm -f out-phase1.lock
