# Backup IaC

PrometheusRule `styx-backup` alerts and kustomization for Velero and home snapshots. Status: IaC done, not run.

Full guide: [docs/operate/backup-schedules.md](../../../docs/operate/backup-schedules.md).

## UTC timeline

- 01:00 CNPG base backup (#24)
- 02:00 OpenBao snapshot (#4)
- 03:00 Velero daily and home snapshots
- 04:30 offsite export (#13)

## Alerts

Stale alerts fire after 26 h (93600 s) without success, or when the metric is absent.

## Rules

- No CNPG `ObjectStore`, `ScheduledBackup` or `Cluster` here (they live in the prod overlay, #24).
- No plain `Secret` with `stringData`; use ExternalSecrets.
- Velero excludes DB PVCs and home volumes (covered by CNPG and CephFS snapshots).
- cephx caps for snapshots: `mds "allow rws path=/volumes/<group>"`, `mon "allow r"`.
- Object Lock: add a lifecycle rule to expire noncurrent versions after the lock period; Velero GC only adds delete markers.
