# Home age-off runbook

Controls: MP-6, SI-12. Decisions: ADR-0035, ADR-0074. `$P` is the portal origin.

Policy: home files untouched for 90 days get a 14-day notice, then move to the RGW bucket `styx-home-archive` (keys `u/<uid>/<relpath>`). Profiles unused for 60 days are deleted after notice; scratch volumes are reclaimed 7 days after stop.

## Enable (turn off dry-run)

The job ships in dry-run: it only logs `ageoff dry-run uid=... action=... files=N`.

1. Confirm the bucket checks below pass and `ARCHIVE_S3_ENDPOINT` is set (the loop does not start without it).
2. Review a dry-run day of logs: `kubectl -n styx logs deploy/styx-backend | grep "ageoff dry-run"`. Check the users and file counts are expected.
3. Set `AGEOFF_DRY_RUN=false` in `deploy/enterprise/backend-patch.yaml`, merge, let Flux roll the backend.
4. First tick posts notices only; files move 14 days later. To go back, set `AGEOFF_DRY_RUN=true`.

The profile and scratch jobs have no dry-run and run whenever the backend leader runs.

## Notices and moves in the audit log

Audit events (ECS `event.dataset=styx.audit`, Elastic):

| Event | Meaning |
| --- | --- |
| `ageoff.move` | files moved to the archive (`detail.files`) |
| `archive.list`, `archive.restore`, `archive.send` | user self-service |
| `profile.reclaim` | profile volume deleted (`detail.volume`) |
| `scratch_reclaim` | scratch volumes removed (`detail.volumes`) |

Notices are in the `notices` table (kinds `ageoff`, `profile_reclaim`, `scratch_reclaim`; `due_at` is the move/delete date; `dismissed_at` set when cancelled or done). A user sees them as the portal banner (`GET /api/notices`).

## Manual restore for a user

Preferred: the user restores from the portal Archive page (`POST /api/archive/restore`).

If the portal is unavailable, use the `styx-archive` RGW user (credentials from secret `rook-ceph-object-user-styx-store-styx-archive`; never paste them into tickets):

```
EP=http://rook-ceph-rgw-styx-store.rook-ceph.svc:80
aws --endpoint-url $EP s3 ls s3://styx-home-archive/u/<uid>/ --recursive
aws --endpoint-url $EP s3 cp s3://styx-home-archive/u/<uid>/<relpath> /homes/<uid>/<relpath>
```

Then set ownership to the user's POSIX uid (ADR-0052, 0066) and record the action in the ticket. A file deleted by mistake is still recoverable as a noncurrent version for 35 days: `aws s3api list-object-versions --bucket styx-home-archive --prefix u/<uid>/`.

## Bucket and retention checks

```
aws --endpoint-url $EP s3api get-object-lock-configuration --bucket styx-home-archive
aws --endpoint-url $EP s3api get-bucket-lifecycle-configuration --bucket styx-home-archive
```

Expect `ObjectLockEnabled: Enabled`, default retention `GOVERNANCE` 30 days, and rule `expire-noncurrent` with `NoncurrentDays: 35`. If missing, re-run the Job `home-archive-bucket-bootstrap` (`deploy/enterprise/rook-ceph/home-archive.yaml`). Also watch RGW capacity: the cold tier must fit in the Ceph budget (ADR-0055).
