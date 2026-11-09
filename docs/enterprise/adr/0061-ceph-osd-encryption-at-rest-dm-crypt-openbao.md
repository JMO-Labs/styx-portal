# ADR-0061: Ceph OSD encryption at rest with dm-crypt, keys in OpenBao

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-11-09
- Decision ID: D60
- Related controls: SC-28, SC-28(1), SC-12
- Related ADRs: ADR-0033, ADR-0042, ADR-0055

## Context

Homes, profiles, volumes and the cold archive hold CUI on Rook-Ceph (ADR-0033). The owner approved the storage ADRs on condition that data on every OSD is encrypted at rest.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Encrypt every Ceph OSD at rest with dm-crypt. OSD encryption keys are held in OpenBao (ADR-0042), not stored on the node.

## Alternatives considered

- No encryption at rest - does not meet SC-28 for CUI.
- Self-encrypting drives only - key custody outside our control.

## Consequences

Positive:

- CUI on Ceph is protected at rest (SC-28, SC-28(1)); keys are centrally managed (SC-12).

Negative:

- dm-crypt costs OSD CPU; covered by the OSD reservations (ADR-0055).
- OSDs cannot start without OpenBao; relies on OpenBao auto-unseal and offline escrow (ADR-0042).

Follow-up work:

- Enable OSD encryption and the OpenBao key backend during Phase 1 Rook-Ceph setup.
