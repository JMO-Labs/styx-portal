#!/usr/bin/env bash
# Build the Phase 1 seed bundle, import it into the kind node's containerd (as RKE2 does from
# agent/images/) and check every lock digest is listed by `crictl images --digests`.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
lock=deploy/enterprise/images/phase1.lock
command -v skopeo >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq skopeo; }
python3 scripts/check_phase1_lock.py --strict "$lock"
scripts/build_seed_bundle.sh out/phase1-seed.tar
node=$(kind get nodes --name spike | head -n1)
docker cp out/phase1-seed.tar "$node:/tmp/phase1-seed.tar"
docker exec "$node" ctr -n k8s.io images import --local /tmp/phase1-seed.tar
listing=$(docker exec "$node" crictl images --digests)
rc=0
while read -r ref; do
  case "$ref" in ''|'#'*) continue ;; esac
  if ! grep -qF "${ref#*@}" <<<"$listing"; then echo "MISSING $ref"; rc=1; fi
done < "$lock"
[ "$rc" = 0 ] && echo "seed bundle import OK: all digests resolvable"
exit "$rc"
