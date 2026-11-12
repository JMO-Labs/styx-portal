# ADR-0065: CephFS homes, UID ownership and freeze on disable

- Status: Proposed
- Date: 2026-11-12
- Decision ID: D64
- Related controls: SC-28, CM-12, CP-10, AC-3

## Context

ADR-0054 moved profiles to CephFS (RWX) and ADR-0052 fixed one immutable POSIX UID per user.
The implementation (home PVCs, quota warning, node-loss script, disable freeze) needs one
record of how these fit together.

Note: the ticket suggested 0062; that number is taken, so the next free one (0065) is used.

## Decision

- **PVC per home and per profile** on StorageClass `ceph-cephfs` (RWX). The CephFS quota
  equals the PVC size (ADR-0034: 10 GB home, 2 GB per app profile).
- **Pods run as the user's POSIX UID** (ADR-0052) with `fsGroup` set, so files on the volume
  are owned by that UID and no other user's pod can write them.
- **80 % warning** comes from Prometheus kubelet volume stats
  (`kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes`); the portal shows
  a banner, and nothing is enforced beyond the quota itself.
- **Node loss**: the `node.kubernetes.io/out-of-service` taint is applied manually after the
  node is fenced ([runbook](../runbooks/node-loss-reattach.md)). No automation taints nodes.
- **Disable freezes the home read-only**: when an account is disabled the home is remounted
  or kept read-only; data is retained, not deleted.

## Alternatives considered

- Automatic out-of-service taint: risks two pods writing one home if the node is only
  partitioned.
- Quota warning from Ceph directly: duplicates kubelet stats already scraped.
- Delete the home on disable: loses data, conflicts with retention.

## Consequences

Positive:

- Ownership is enforced by POSIX UID; quota and alert use one number.
- Node-loss recovery is safe against split-brain writes.

Negative:

- Recovery after node loss needs a human to fence and taint.
- Quota is per PVC, so resizing means a PVC change.

Follow-up work:

- Runbook: [node-loss-reattach.md](../runbooks/node-loss-reattach.md), [rook-ceph.md](../runbooks/rook-ceph.md).
