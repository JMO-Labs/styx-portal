#!/usr/bin/env bash
# Build the Phase 1 seed bundle, import it into the kind node's containerd (as RKE2 does from
# agent/images/) and check every lock digest is listed by `crictl images --digests`.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
lock=deploy/enterprise/images/phase1.lock
command -v skopeo >/dev/null || { sudo apt-get update -qq && sudo apt-get install -y -qq skopeo; }
python3 scripts/check_phase1_lock.py --strict "$lock"
scripts/build_seed_bundle.sh out/phase1-seed.tar
du -h out/phase1-seed.tar
df -h . | tail -n1
node=$(kind get nodes --name spike | head -n1)
# Stream via stdin: the kind node's /tmp is a tmpfs, so copying the archive there hides it from ctr,
# and streaming avoids a second 7 GB copy on the node.
docker exec -i "$node" ctr -n k8s.io images import --local - < out/phase1-seed.tar
# --no-trunc: crictl shortens digests otherwise and the full-digest grep below never matches.
listing=$(docker exec "$node" crictl images --digests --no-trunc)
rc=0
while read -r ref; do
  case "$ref" in ''|'#'*) continue ;; esac
  if ! grep -qF "${ref#*@}" <<<"$listing"; then echo "MISSING $ref"; rc=1; fi
done < "$lock"
[ "$rc" = 0 ] && echo "seed bundle import OK: all digests resolvable"
exit "$rc"
