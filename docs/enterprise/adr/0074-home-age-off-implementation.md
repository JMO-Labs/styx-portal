# ADR-0074: Home age-off implementation choices

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D73
- Related controls: MP-6, SI-12, CM-12, SC-28
- Refines: ADR-0035, ADR-0054, ADR-0059, ADR-0066

## Context

ADR-0035 fixes the policy (90 d stale + 14 d notice, RGW cold tier, self-restore, profile 60 d, scratch 7 d). The implementation left choices open. This records them for owner acceptance. (The ticket proposed number 0070; taken by DLP, so this is 0074.)

## Decision

1. **The backend mounts the CephFS homes root at `/homes`.** The `styx-homes` PVC is mounted in the backend pod (`deploy/enterprise/backend-patch.yaml`); `HOMES_ROOT` defaults to `/homes`. The age-off job and the archive API read and write homes directly, with `O_NOFOLLOW` walks so a user cannot redirect a move through a symlink.
2. **S3 key layout is `u/<uid>/<relpath>`.** One bucket, `styx-home-archive`, on the RGW store `styx-store`, with the per-user prefix `u/<uid>/` and the file's path relative to the home (`backend/app/services/archive_store.py`). The original mtime is kept as object metadata and restored on download.
3. **Object lock GOVERNANCE, 30 d default retention.** The bucket is created with object lock; the default rule is `GOVERNANCE` for 30 days. Lifecycle expires noncurrent versions after 35 days. GOVERNANCE (not COMPLIANCE) lets an administrator with the bypass permission correct a mistake; users cannot delete locked versions. IaC: `deploy/enterprise/rook-ceph/home-archive.yaml`.
4. **Dry-run is on by default.** `AGEOFF_DRY_RUN` (default `true`) makes the job plan and log only: no notice, no upload, no delete. Enabling is a deliberate operator action (runbook). The loop starts only when `ARCHIVE_S3_ENDPOINT` is set, runs on the leader only, every `AGEOFF_INTERVAL_S` (default 86400).
5. **Notices live in a portal table.** The `notices` table (migration 0018, unique per user, kind, key) feeds the portal banner (`GET /api/notices`, dismiss). Kinds: `ageoff`, `profile_reclaim`, `scratch_reclaim`. No email or Matrix message is required (ADR-0059).
6. **Only files stale at notice time move.** A file is moved only if it was already stale when the notice was sent and the 14 days have passed without it being opened or modified. Newly stale files start a new cycle. A failed upload leaves the file in place.
7. **Profile 60 d and scratch 7 d are separate jobs.** `profile_reclaim` deletes a profile unused for 60 days after a 14-day notice (use since the notice cancels it; `profile.reclaim` audit event). `scratch_reclaim` removes scratch volumes of instances stopped for more than 7 days, hourly, and posts a notice after the fact (`scratch_reclaim` audit event). These two jobs have no dry-run switch.
8. **Self-restore is a portal feature.** `GET /api/archive`, `POST /api/archive/restore` and `POST /api/archive/send` act only on the caller's own `u/<uid>/` prefix and are audited (`archive.list`, `archive.restore`, `archive.send`).

## Alternatives considered

- COMPLIANCE lock: no recovery from operator error.
- Dry-run switch on profile/scratch jobs: those delete volumes, not user files, and are notice-gated; not added.
- Mail notices: needs SMTP, which is optional (ADR-0059).

## Consequences

Positive: one tested path from stale file to cold tier and back; every move and restore is audited; a mistaken enablement can be reversed from the bucket within the lock window.

Negative: the backend holds write access to all homes and RGW credentials; archive restores overwrite nothing but need free quota in the home; noncurrent versions are dropped after 35 days.
