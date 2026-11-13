#!/usr/bin/env bash
# Build one OCI archive of every Phase 1 image from phase1.lock (CI only; needs skopeo + registry
# access). `skopeo copy --all` keeps manifest digests. Usage: build_seed_bundle.sh [out.tar]
set -euo pipefail
cd "$(dirname "$0")/.."
lock=deploy/enterprise/images/phase1.lock
out=${1:-out/phase1-seed.tar}
python3 scripts/check_phase1_lock.py --strict "$lock"
mkdir -p "$(dirname "$out")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
n=0
while read -r ref; do
  case "$ref" in ''|'#'*) continue ;; esac
  n=$((n + 1))
  # One OCI layout per image so the archive index keeps the digest annotation.
  skopeo copy --all "docker://$ref" "oci:$work/img$n:seed"
  # Name the image by its digest ref so containerd/crictl list it with this digest.
  jq --arg r "$ref" '.manifests |= map(.annotations = {"io.containerd.image.name": $r, "org.opencontainers.image.ref.name": $r})' \
    "$work/img$n/index.json" > "$work/idx" && mv "$work/idx" "$work/img$n/index.json"
done < "$lock"
# Merge layouts: all blobs into one dir, all index entries into one index.json.
mkdir -p "$work/all/blobs/sha256"
echo '{"imageLayoutVersion":"1.0.0"}' > "$work/all/oci-layout"
for d in "$work"/img*/; do cp -an "$d"blobs/sha256/. "$work/all/blobs/sha256/"; done
jq -s '{schemaVersion:2,mediaType:"application/vnd.oci.image.index.v1+json",manifests:(map(.manifests)|add)}' \
  "$work"/img*/index.json > "$work/all/index.json"
# A plain tar of an OCI layout is exactly what the oci-archive: transport reads (skopeo oci-archive:$out).
tar -C "$work/all" -cf "$out" .
echo "wrote $out ($n images)"
