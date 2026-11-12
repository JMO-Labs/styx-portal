# Phase 1 image seed bundle (issue #25)

- `phase1.images`: `repo:tag` for every Phase 1 image (tags match the pinned IaC).
- `phase1.lock`: the same images as `repo@sha256:<digest>`. `scripts/check_phase1_lock.py` fails on
  tag-only refs, placeholders and unknown repos; `--strict` also fails on any image missing from the lock.
- `scripts/resolve_phase1_digests.sh` (CI, needs skopeo): regenerates the lock from the tags.
- `scripts/build_seed_bundle.sh` (CI): one OCI archive from the lock, for `agent/images/` on RKE2.
- `scripts/kind/10-seed-bundle-import.sh`: kind-spike import plus `crictl images --digests` check.
- `deploy/enterprise/harbor/seed-push-job.yaml`: pushes the archive's images into Harbor.

Open: `traefik` has no digest yet (nothing in-tree pins it). Run the resolve script in CI and commit
the result; until then `--strict` (used by the build script and kind spike) fails by design.
