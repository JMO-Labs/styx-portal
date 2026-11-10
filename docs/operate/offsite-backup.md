# Offsite backup (encrypted export)

The offsite copy for the enterprise profile (ADR-0037, D37). Each night a Kopia
CronJob reads the newest CephFS subvolume snapshots (taken by the nightly home and
profile snapshots) read-only. It writes them to one Kopia repository in an S3 bucket
with Object Lock. Kopia encrypts and deduplicates on the client, so each run uploads
only changed chunks. The bucket never sees plaintext.

The component is opt-in: `deploy/k8s/offsite-export/` is **not** part of
`deploy/k8s/kustomization.yaml`, so the homelab profile does not change.

| Piece | What it does |
|---|---|
| `styx-offsite-export` CronJob | `30 4 * * *` UTC, `offsite-export.sh export` |
| `styx-offsite-verify` CronJob | `30 10 * * *` UTC, `offsite-export.sh verify` (1% file sample daily, full `content verify` weekly) |
| `ExternalSecret styx-offsite-export` | `KOPIA_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` from OpenBao KV `backup/offsite/kopia` (D42) |
| `PersistentVolume styx-offsite-snapshots` | Static ceph-csi volume on the CephFS `volumes` root, `ReadOnlyMany`, read-only cephx user |
| `CiliumNetworkPolicy` | Egress to kube-dns and the bucket FQDN on 443 only |
| `PrometheusRule styx-offsite` | `StyxOffsiteExportFailed`, `StyxOffsiteExportStale` (> 26 h, RPO 24 h), `StyxOffsiteVerifyFailed`, `StyxOffsiteVerifyStale` (> 50 h) |

## Prerequisites

- Rook-Ceph with CephFS (#3) and the nightly `nightly-YYYY-MM-DD` subvolume snapshots (#9).
- OpenBao and External Secrets with a `ClusterSecretStore` named `openbao` (#4).
- Cilium (for `toFQDNs`) and kube-prometheus-stack with kube-state-metrics.
- A bucket that supports **S3 Object Lock** (created with locking on) and holds a
  CUI authorization. The owner chooses it before deployment.
- A bucket credential that can write and read objects. It must **not** have
  `s3:BypassGovernanceRetention`, and it must not be able to change the bucket's lock
  configuration or delete the bucket.
- A bucket **lifecycle rule** on `OFFSITE_S3_PREFIX` with `NoncurrentVersionExpiration`
  set to `OFFSITE_LOCK_DAYS` (Kopia recommends matching the retention period) and
  `ExpiredObjectDeleteMarker`. An Object Lock bucket is always versioned, and Kopia's
  garbage collection deletes blobs with a plain `DELETE`. That only adds a delete
  marker: without the rule, every deleted blob stays (and is billed) forever. The
  bucket owner sets it once, for example:

  ```sh
  # MinIO
  mc ilm rule add --prefix styx/ --noncurrent-expire-days 35 --expire-delete-marker <alias>/<bucket>
  # AWS S3
  aws s3api put-bucket-lifecycle-configuration --bucket <bucket> --lifecycle-configuration \
    '{"Rules":[{"ID":"styx-offsite-noncurrent","Status":"Enabled","Filter":{"Prefix":"styx/"},
      "NoncurrentVersionExpiration":{"NoncurrentDays":35},
      "Expiration":{"ExpiredObjectDeleteMarker":true}}]}'
  ```

  Keep the days equal to `OFFSITE_LOCK_DAYS` if you change it. Object Lock still wins:
  a locked version is not removed before its lock expires.

## Configuration

All settings live in `deploy/k8s/offsite-export/params.env`. A `configMapGenerator`
turns it into the ConfigMap `styx-offsite-params`.

| Key | Default | Meaning |
|---|---|---|
| `OFFSITE_CIPHER` | `AES256-GCM-HMAC-SHA256` | Or `CHACHA20-POLY1305-HMAC-SHA256`. It is fixed when the repository is created. |
| `OFFSITE_S3_ENDPOINT` | `s3.example.invalid` | Bucket endpoint host. Also set it in `networkpolicy.yaml` (`toFQDNs`). |
| `OFFSITE_S3_BUCKET` | `styx-offsite.example.invalid` | Bucket name. |
| `OFFSITE_S3_PREFIX` | `styx/` | Object prefix for the repository. |
| `OFFSITE_S3_REGION` | `us-gov-west-1` | Bucket region. |
| `OFFSITE_S3_DISABLE_TLS` | `false` | Only the CI MinIO test sets this. Never change it in a real deployment. |
| `OFFSITE_KEEP_DAILY` / `_WEEKLY` / `_MONTHLY` | `30` / `8` / `12` | Kopia global retention policy, set by `init`. |
| `OFFSITE_LOCK_DAYS` | `35` | Object Lock period (COMPLIANCE). It must be longer than the full-maintenance interval (7 days) plus 1 day. |
| `OFFSITE_ORPHAN_DAYS` | `1095` | `export` deletes every snapshot of a source that is no longer on disk (a deleted home) once its newest snapshot is older than this. `1095` matches Kopia's `keep-annual 3` horizon for files deleted from a live home. |
| `OFFSITE_SNAP_ROOT` | `/snapshots` | Mount path of the CephFS `volumes` root. |
| `OFFSITE_SNAP_PREFIX` | `nightly-` | Snapshot name prefix. Names must be `<prefix>YYYY-MM-DD`. |
| `OFFSITE_GROUPS` | empty | Space-separated subvolume groups to export (for example `homes profiles`). Empty means every group. Set it when other groups, such as ceph-csi's `csi`, have no nightly snapshots: their subvolumes would otherwise fail the run. |
| `OFFSITE_VERIFY_PERCENT` | `1` | Share of files that the daily verify re-reads and decrypts. |
| `OFFSITE_FULL_VERIFY_DOW` | `7` | Weekday (`date -u +%u`, 1 = Monday) for the full `content verify`. |

Also replace the placeholders in `pv.yaml` (`clusterID`, `fsName`) and create the
read-only cephx user's Secret `styx-offsite-cephx-ro` (keys `userID`, `userKey`) in
namespace `styx-backup`. For example:

```sh
ceph auth get-or-create client.styx-offsite-ro \
  mon 'allow r' mds 'allow r' osd 'allow r tag cephfs data=<fsName>'
```

The image tag is pinned in `kustomization.yaml` (`images:`). Mirror it to Harbor and
sign it when ADR-0029 lands.

### Namespace and pod security

User homes are `0700` and each belongs to a different UID. The job therefore runs as
UID 0 with every capability dropped except `DAC_READ_SEARCH` (read any file). It
also uses a read-only root filesystem, a read-only snapshot volume and no privilege
escalation. Pod Security `baseline` (the `styx` namespace) does not allow
`DAC_READ_SEARCH`. The component therefore creates its own namespace, `styx-backup`,
with `pod-security.kubernetes.io/enforce: privileged` and `warn: restricted`. Keep
other workloads out of that namespace. If cluster policy (Kyverno) forbids the label,
add an exemption scoped to these two CronJobs.

### How export works

For each `<group>/<subvol>` under `OFFSITE_SNAP_ROOT`, the job skips Ceph's internal
`_`-prefixed dirs (`_deleting`, `_index`, ...) except `_nogroup`, and groups not in
`OFFSITE_GROUPS` when that is set. Then it:

1. Picks the newest `.snap/<prefix>YYYY-MM-DD/<uuid>` by name. It ignores other names, such as `manual-x`,
   and names whose date is invalid or after today (UTC), so a bogus name cannot mask a stale export.
2. Runs `kopia snapshot create <path> --override-source=styx@offsite:/export/<group>/<subvol> --tags=snap:<name>`.
   The stable source name lets Kopia find the previous snapshot, so the run is incremental.

The job fails, and the alert fires, in these cases:

- There are no subvolumes at all.
- A subvolume has no matching snapshot.
- A subvolume's newest snapshot is older than yesterday (UTC). This is the RPO guard.
- An upload fails. The job still tries every other subvolume first, then names the
  failed ones in its log, for example `failed subvolumes: homes/alice(upload)`.

## First-time init

Run `init` once from a one-off Job, after the Secret exists:

```sh
kubectl kustomize deploy/k8s/offsite-export | kubectl apply -f -
kubectl -n styx-backup create job offsite-init --from=cronjob/styx-offsite-export \
  --dry-run=client -o yaml | sed 's/- export/- init/' | kubectl apply -f -
kubectl -n styx-backup logs -f job/offsite-init
```

`offsite-export.sh init` refuses to run if it can already connect to a repository at
the target. Otherwise it runs these steps:

1. `kopia repository create s3 ... --encryption=$OFFSITE_CIPHER --retention-mode=COMPLIANCE --retention-period=${OFFSITE_LOCK_DAYS}d`
2. `kopia maintenance set --extend-object-locks=true`
3. `kopia policy set --global --keep-daily/--keep-weekly/--keep-monthly`

All runs use the fixed identity `styx@offsite`, so the export job owns maintenance.
Kopia's other global defaults (`keep-latest 10`, `keep-hourly 48`, `keep-annual 3`)
stay in force. Set `--keep-annual=0` if a snapshot must not be kept for up to 3 years.

The script refuses a `KOPIA_PASSWORD` shorter than 32 characters. It never prints
the password or puts it on a command line. Kopia and the S3 client read it, and the
`AWS_*` keys, from the environment.

## Offline escrow envelope

A sealed envelope in the safe (D25/D42) holds everything needed to restore without
OpenBao or the cluster, because a site loss can take both:

- the repository password (`KOPIA_PASSWORD`)
- the endpoint, region, bucket and prefix
- the bucket lifecycle rule (prefix and noncurrent-expiry days), to set it again on a rebuilt or migrated bucket
- the Kopia version in use (the `images:` tag)
- this one-page restore procedure

Bucket read credentials come from the bucket owner's account (break-glass). They are
not in the envelope. Update the envelope after every key rotation.

### Restore procedure (one page)

1. On any Linux machine, install the escrowed Kopia version.
2. Set `KOPIA_PASSWORD`, `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in your shell
   environment (not on the command line).
3. Connect read-only, so the restore host never runs maintenance:
   `kopia repository connect s3 --readonly --bucket=<b> --endpoint=<e> --region=<r> --prefix=<p> --override-username=styx --override-hostname=restore`
4. List the snapshots: `kopia snapshot list --all`. Sources are
   `styx@offsite:/export/<group>/<subvol>`, and the tag `snap:` names the CephFS snapshot.
5. Restore as root, to keep owners and modes:
   `kopia snapshot restore <snapshot-id> /restore/<group>/<subvol>`
6. Copy the data into the target subvolume. Run `kopia snapshot verify` if in doubt.

The restore harness (#15) runs this procedure end to end, and the DR runbook (#14)
reuses it.

## Key rotation

`kopia repository change-password` only re-wraps the format blob. The master key stays
the same, and Object Lock keeps the old format blob, so the old password still opens
the data. To rotate for real:

1. Create a new repository under a new prefix with a new password, using `init`.
2. Point `params.env` and OpenBao at it, and update the escrow envelope.
3. Pick a delete date for the old repository. It never ages out on its own: it gets
   no new snapshots, and Kopia measures retention from each source's newest snapshot.
   The date must be at least `OFFSITE_LOCK_DAYS` after the last export to it, and late
   enough to cover the history you must keep (12 monthly snapshots by default).
4. On that date, delete the old prefix with the bucket owner's account. The bucket is
   versioned, so the lifecycle rule removes the noncurrent versions
   `NoncurrentDays` later. This is what actually erases the data.
5. Then destroy every copy of the old password: the old OpenBao KV v2 versions of
   `backup/offsite/kopia` (`bao kv destroy -versions=<n>`; a later version on the same
   path does not remove them) and the old escrow envelope. Only then is anything the
   delete missed crypto-shredded. Do not do this earlier: until the delete date the old
   repository is still your restore source.

## Deleted users

When an account is deleted, its home goes too (D34). Its offsite source then gets
no new snapshots. Kopia measures retention from a source's own newest snapshot, so
on its own it would keep that source's last snapshots forever. `export` therefore
deletes all snapshots of a source that is no longer on disk once its newest snapshot
is older than `OFFSITE_ORPHAN_DAYS` (default 1095 days, the same horizon as Kopia's
`keep-annual 3` for a file deleted from a live home). Kopia's maintenance then
garbage-collects the unreferenced blobs, which only adds S3 delete markers. The
bucket lifecycle rule (see Prerequisites) removes the now noncurrent versions
`NoncurrentVersionExpiration` days later, and never before their Object Lock expires.
Kopia's GC deletes only whole pack blobs with no live content left, so this bound
holds for whole packs only: a deleted user's data in packs of their own stays offsite
for up to `OFFSITE_ORPHAN_DAYS` plus about a week of maintenance GC delay plus the
noncurrent-expiry days (`OFFSITE_LOCK_DAYS`, 35 by default). Without the lifecycle
rule it stays forever. Lower `OFFSITE_ORPHAN_DAYS` if the data-retention notice
needs a shorter period, and record the value there.

Chunks in a pack shared with live, deduplicated data (for example content common to
several homes) are not removed: full maintenance rewrites only mostly-empty packs, so
such a pack is never deleted. Those chunks stay in the bucket, encrypted but readable
with the escrowed key, until the repository is rotated. Rotation (see Key rotation:
new repository, delete the old prefix, destroy the old password) is the only
guaranteed erase: the prefix delete plus the lifecycle rule removes the data, and
destroying the old password crypto-shreds any copy left. If a hard erase deadline is
needed, it is set by how often the repository is rotated. No cadence is set yet; that
is an owner decision.

A subvolume that is missing only for a while (for example a mount problem) is safe:
its source is purged only after its newest snapshot is older than
`OFFSITE_ORPHAN_DAYS`. A run that finds no subvolumes at all fails before purging.

## Integrity and alerts

- Every day the verify job re-reads `OFFSITE_VERIFY_PERCENT` of the files. Over a
  year this covers most of the data. Once a week it runs `kopia content verify`.
- Kopia locks data and index blobs (`p*`, `q*`, `x*`, `kopia.repository`). It
  deliberately leaves its own `_log_*` and `kopia.maintenance` blobs unlocked.
- The alerts come from kube-state-metrics (`kube_job_failed`,
  `kube_cronjob_status_last_successful_time`). The stale alerts also fire before the
  first success, which is expected right after install.

## Cost check (D05/D37)

The worst case is about 2 TB (200 users × 10 GB homes plus profiles), before dedup and
compression. Object Lock and 30+ days of history keep extra versions. Without the
noncurrent-version lifecycle rule (see Prerequisites), every blob that Kopia's GC
deletes stays billed forever and storage grows without bound; with it, deleted blobs
are billed for about `OFFSITE_LOCK_DAYS` more. GC only drops whole packs, so a
pack that still holds some live content stays billed in full until rotation.
Before you deploy, check the chosen provider's storage, request and egress pricing against the
accepted budget of about $20-50/month (D05/D37).

## Testing

- `backend/tests/test_k8s_offsite_manifests.py` checks the manifests, and
  `backend/tests/test_offsite_export_script.py` runs the script with a fake `kopia`.
- `backend/tests/integration/test_offsite_minio.py` (`OFFSITE_IT=1`, CI job
  `offsite-integration`) runs real Kopia against MinIO with Object Lock. It covers
  backup, verify, a byte-identical restore and an incremental second run. It also
  shows that deleting a locked version is refused, that a wrong password cannot
  connect, that orphaned sources are purged, and that the bucket's noncurrent-version
  lifecycle rule coexists with Object Lock.

## Known issues

- **Not in GitHub CI yet.** The `kustomize build | kubeconform -strict` check and the
  MinIO integration suite run as the GitLab jobs `offsite-manifests` and
  `offsite-integration` in `.gitlab-ci.yml`, which have not run in a pipeline yet.
  GitHub CI runs only the manifest and script unit tests. Adding the two jobs to
  `.github/workflows/ci.yml` needs a token with `workflow` scope (patch in PR #126).
  Until then, run both locally before you change the component.
- **`StyxOffsiteExportFailed` stays firing after a later success.** It matches
  `kube_job_failed`, and the CronJob keeps up to 3 failed Jobs
  (`failedJobsHistoryLimit: 3`). After you fix the cause and a run succeeds, delete the
  failed Job (`kubectl -n styx-backup delete job <name>`) to clear the alert. The same
  applies to `StyxOffsiteVerifyFailed`.
- **Password length counts bytes.** Under `dash` (the image's `/bin/sh`),
  `${#KOPIA_PASSWORD}` counts bytes, so a password of 31 multibyte characters passes the
  32-character check. Generate the password as random ASCII (for example
  `openssl rand -base64 48`).
- **Orphan names with `&`, `<` or `>`.** Kopia's `--json` output escapes these, so
  the orphan purge would look for the wrong source name and never purge it. Ceph
  subvolume names are normally `[A-Za-z0-9_.-]`; keep them that way.
- **Not deployed.** A live run needs Rook-Ceph (#3), OpenBao and External Secrets (#4)
  and the nightly snapshots (#9). The bucket and its CUI authorization are not chosen yet.
