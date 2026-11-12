# Runbook: Ceph OSD encryption (dm-crypt, keys in OpenBao)

Operates the encrypted OSDs of `deploy/enterprise/rook-ceph/` (ADR-0061, ADR-0033, ADR-0042).
IaC only, not deployed. Every `storageClassDeviceSets` entry has `encrypted: true`; Rook LUKS-formats
each OSD PVC and stores its key encryption key (KEK) in OpenBao, KV v2 mount `rook/`, path
`rook/data/rook-ceph-osd-encryption-key-<pvc-name>`. Access is limited by the OpenBao policy
`deploy/enterprise/openbao/policies/rook-ceph.hcl` (role `rook-ceph`, Kubernetes auth).
The behaviour below is proven by `scripts/kind/10-ceph-kms.sh` (CI job `kind-spike`).

## Why encryption and KMS cannot change after first deploy

Encryption is chosen when an OSD is created. Rook cannot LUKS-format a live OSD, and the KMS
connection (`security.kms`) is baked into every OSD's key lookup. So:

- Turning `encrypted` on for existing OSDs needs a PVC OSD migration (`storage.migration`),
  replacing OSDs one at a time while Ceph re-replicates. Plan it as a data move, not a flag flip.
- Changing the KMS (address, backend path, provider) means wiping and rebuilding every OSD.
- Therefore: no pools or PVCs before encryption and the OpenBao backend are applied
  ([rook-ceph.md](rook-ceph.md) install order).

dm-crypt CPU cost is inside the OSD reservations (ADR-0055). FIPS validation of dm-crypt depends on
the node OS kernel, so SC-13 stays open compliance debt (ADR-0011 exception references pending).

## KEK rotation

`security.keyRotation` (schedule `0 2 1 * *`, 02:00 on the 1st) makes Rook rotate each OSD's KEK
and write a new version of the same KV path. Normal operation needs no action.

Check after the first run:

```bash
bao kv list -mount=rook
bao kv metadata get -mount=rook rook-ceph-osd-encryption-key-<pvc-name>   # current_version rose
kubectl -n rook-ceph get cronjob,job | grep -i rotat
```

- Do not delete old KV versions or run `bao kv destroy`/`metadata delete` on `rook/`. The policy
  allows it; do not use it. Old versions are cheap and may be needed from a raft snapshot.
- Rotation writes to OpenBao, so it fails during an outage; it retries on schedule.
- A new version is only safe once the nightly raft snapshot (02:00 UTC, ADR-0042) has run after it.
  Before a planned manual rotation, take a snapshot first (see [openbao.md](openbao.md)).

## OpenBao outage

Behaviour:

- Running OSDs keep their dm-crypt mapping and continue to serve I/O.
- New or restarted OSD pods (node reboot, upgrade, crash) hang in `Init` until OpenBao returns.
- Keep `removeOSDsIfOutAndSafeToRemove: false` (set in `cephcluster.yaml`) so the operator never
  zaps OSDs that are merely waiting for keys.

Detect: alert on OSD pods stuck in `Init`:

```bash
kubectl -n rook-ceph get pods -l app=rook-ceph-osd | grep -E 'Init|Pending'
kubectl -n openbao get pods
```

Recover:

1. Restore OpenBao: 3 raft replicas on control-plane local PVs, auto-unseal via the static seal
   key (ADR-0042). See [openbao.md](openbao.md); if the data is lost, use its Snapshot restore.
2. Verify `bao status` is unsealed on all replicas.
3. Do nothing to the OSDs. Pods in `Init` retry and start on their own; confirm with
   `ceph status` reaching HEALTH_OK.

Do not drain or reboot storage nodes during an OpenBao outage: those OSDs will not come back
until the KEK is readable.

## Break-glass: manual unlock from a raft snapshot

Use only when OpenBao cannot be recovered in place but the data on the disks must be read
(for example, rescuing data while OpenBao is rebuilt). **Key loss means data loss**: without the
KEK the LUKS volume is unrecoverable. The escrow of the seal key and the offsite snapshots
(ADR-0042, ADR-0037) are the only backup of the KEKs.

1. Get a snapshot and the static seal key that was current when it was taken
   (`<key-id>.key`, from escrow). Restore it into an isolated OpenBao, never into the live
   cluster, following [openbao.md](openbao.md) Snapshot restore (`bao operator raft snapshot
   restore -force`, root token from escrow).
2. Read the KEK for the OSD's PVC (`<pvc-name>` is the OSD PVC, see
   `kubectl -n rook-ceph get pvc`):

    ```bash
    bao kv get -mount=rook -format=json rook-ceph-osd-encryption-key-<pvc-name> \
      | jq -r '.data.data | to_entries[0].value' > /dev/shm/kek
    chmod 600 /dev/shm/kek
    ```

    Use a RAM-backed path, never a disk, and do not paste the key into tickets or chat.
3. On the node (OSD pod scaled to 0, device not in use), open the volume. The Rook PVC device is
   the local NVMe (by-id path in `nvme-inventory.yaml`):

    ```bash
    cryptsetup luksOpen --key-file /dev/shm/kek /dev/disk/by-id/nvme-<id> osd-rescue
    ```

    If the stored value is base64, decode it first (`base64 -d`). The result is under
    `/dev/mapper/osd-rescue` (a BlueStore device; use `ceph-bluestore-tool` or
    `ceph-volume raw` to inspect or start it).
4. Clean up: `cryptsetup luksClose osd-rescue`, `shred -u /dev/shm/kek`, destroy the isolated
   OpenBao, and record the access in the audit log.

If the current KV version fails, try earlier versions from the snapshot
(`bao kv get -version=<n>`): the disk header may predate a rotation.

## Add or replace an NVMe

The mechanics are in [rook-ceph.md](rook-ceph.md) (inventory, `gen_nvme_pvs.py`, node prep).
Encryption adds:

1. Edit `nvme-inventory.yaml`, regenerate; the generated `cephcluster.yaml` sets `encrypted: true`
   on every device set, and tests reject any unencrypted set.
2. Prep the disk (`sgdisk --zap-all`, `blkdiscard`). A previously used encrypted disk must be
   wiped fully so no old LUKS header remains.
3. Apply `kubectl apply -k deploy/enterprise/rook-ceph/`. The new OSD pod formats LUKS and writes
   its KEK to `rook/` at first start, so OpenBao must be up.
4. Replacement: purge the failed OSD first (`ceph osd out`, wait for rebalance,
   `ceph osd purge`). Its old KV key can stay until after the next verified snapshot.
5. Confirm a new `rook-ceph-osd-encryption-key-*` entry exists in `rook/` and that a snapshot
   taken afterwards contains it before the disk is trusted with data.

## Compliance debt

- SC-13: dm-crypt is not FIPS-validated by us; depends on the OS kernel. Open until ADR-0011
  exception references are cited.
- The KEKs have no copy outside OpenBao raft snapshots; the 2-of-3 recovery threshold awaits the
  owner's escrow custody confirmation (ADR-0042).
