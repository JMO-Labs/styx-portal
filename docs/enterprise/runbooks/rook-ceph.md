# Runbook: Rook-Ceph on worker NVMe

Operates the Rook-Ceph cluster in `deploy/enterprise/rook-ceph/` (ADR-0033, ADR-0055). IaC only,
not deployed. Hostnames, serials and by-id paths in `nvme-inventory.yaml` are placeholders the
site fills in.

!!! warning "Encryption (#20) must land first"
    OSD encryption with the OpenBao Vault KMS (#20, ADR-0061) must be in place **before any data
    is written**. The KMS cannot be changed after OSDs are created; changing it means wiping and
    rebuilding every OSD. Do not create pools or PVCs until #20 is applied.

## Install order

1. OpenBao up and unsealed (see [openbao.md](openbao.md)); encryption/KMS (#20) applied.
2. Node prep on every storage worker (below).
3. Rook operator via Helm with `operator-values.yaml`.
4. `kubectl apply -k deploy/enterprise/rook-ceph/` (local PVs, CephCluster, throttle, alerts).
5. Wait for `ceph status` HEALTH_OK, then apply pools/StorageClasses.

## Node prep (once, outside Rook)

Rook never wipes disks. On each node, per data NVMe (never the OS disk), once before first use:

```bash
sgdisk --zap-all /dev/disk/by-id/nvme-<id>
blkdiscard /dev/disk/by-id/nvme-<id>
```

Double-check the by-id path against `os_disk` in the inventory first. This is destructive.

## Add or replace an NVMe

1. Edit `deploy/enterprise/rook-ceph/nvme-inventory.yaml` (new by-id path, size).
2. Regenerate: `python3 scripts/enterprise/gen_nvme_pvs.py` (rewrites `local-pvs.yaml` and
   `cephcluster.yaml`; the generator refuses OS disks and unstable names).
3. Prep the new disk (above), then `kubectl apply -k deploy/enterprise/rook-ceph/`.
4. For a replacement, first purge the failed OSD (`ceph osd out`, wait for rebalance, remove).

## Force recovery {#force-recovery}

A CronJob (`ceph-mclock-throttle`, every 15 min) favours clients Mon-Fri 07:00-19:00
`America/New_York` and recovery otherwise. The window is configurable in the ConfigMap
`ceph-throttle-config` (`window`).

Alert `CephPGsDegraded` fires after PGs stay degraded for 4 h. Decide whether to speed recovery,
e.g. PGs at `min_size` with a second failure risking data loss:

```bash
kubectl -n rook-ceph patch cm ceph-throttle-config --type merge -p '{"data":{"force":"high_recovery_ops"}}'
```

The next run (up to 15 min) applies it. Clear it afterwards with `"force":""`. Only
`high_client_ops` and `high_recovery_ops` are accepted; anything else is ignored.

Alert `CephThrottleJobFailing` fires when the CronJob fails or has not succeeded for over 1 h;
check `kubectl -n rook-ceph get cronjob,job` and the pod logs.

## NOTES

- Node loss and CephFS home reattach: [node-loss-reattach.md](node-loss-reattach.md).
- Registry: images use the placeholder `harbor.example.internal`; override it per site
  (Helm values, generator constant, kustomize `images`).
- OpenBao must not use Ceph storage.

## Compliance debt

Unchanged: gate R05 waived by the owner 2026-11-09. FIPS/STIG references (SC-13, CM-6) are still
missing, and ADR-0011 stays Proposed. Not for accredited environments until these close.
