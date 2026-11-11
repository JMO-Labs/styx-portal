# Backup schedules

Status: IaC written, not yet run (no deployment). See control CP-9 in the [control matrix](../enterprise/control-matrix.md) and ADR-0037.

## UTC timeline

| Time (UTC) | Job | Source |
|---|---|---|
| continuous | CNPG WAL archiving | CNPG plugin (prod Cluster overlay, #24) |
| 01:00 | CNPG base backup | `ScheduledBackup` (#24) |
| 02:00 | OpenBao snapshot | #4 |
| 03:00 | Velero daily backup | `deploy/enterprise/backup` |
| 03:00 | Home directory CephFS snapshots | `deploy/enterprise/backup` |
| 04:30 | Offsite encrypted export | #13 |

The export runs after all snapshots so it picks up the night's data. The CNPG objects live only in the prod Cluster overlay, never in `deploy/enterprise/backup/`; a test enforces this. The #15 recovery Cluster has no `spec.plugins` or `spec.backup`.

## Alerts

The *Stale* alerts fire when the last success is older than 26 h (93600 s) **or the metric is absent**, so a broken exporter is not silent. They wait 30 min before firing.

| Alert | Meaning |
|---|---|
| CnpgBackupStale | No CNPG backup in 26 h |
| CnpgBackupFailed | Latest CNPG backup failed |
| CnpgWalArchivingFailing | WAL archive stalled over 15 min or failing (RPO at risk) |
| VeleroBackupStale | No successful `daily` Velero backup in 26 h |
| VeleroBackupFailed | Velero backup failed or partially failed in the last hour |
| VeleroBslUnavailable | Backup storage location unreachable |
| HomeSnapshotsStale | No successful `styx-home-snapshots` run in 26 h |
| HomeSnapshotsFailed | A snapshot job failed |

## What Velero excludes

Velero backs up cluster state only. It excludes PVC contents of the database (CNPG backs that up with WAL, which is consistent) and the home directories (CephFS snapshots cover those, and file-level copies of a live volume are not crash-consistent). Secrets come from OpenBao via External Secrets, so they are restored from #4, not Velero.

## Minimal cephx caps for snapshots

The snapshot job only needs to create and remove snapshots on the home subvolume group:

```
mds "allow rws path=/volumes/<group>"
mon "allow r"
```

No OSD caps are required for CephFS snapshot creation. Do not reuse the CSI provisioner key.

## Object Lock lifecycle

On a versioned bucket with Object Lock, Velero garbage collection only adds delete markers; the locked versions stay. Storage therefore grows until locks expire. Add a lifecycle rule to **expire noncurrent versions after the lock period** (for example, lock of 30 days gives `NoncurrentVersionExpiration` of 31 days). This is not blocking.

## Compliance note

SC-28: only server-side encryption protects barman-cloud objects and Velero metadata. Offsite export encryption (#13) is separate.
