# ADR-0055: Ceph OSD reservations and throttled recovery

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D55
- Related controls: SC-5, CP-2

## Context

Ceph shares worker nodes with desktops (ADR-0033).

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Reserve CPU and memory per node for OSDs, and throttle recovery/backfill during business hours. (Builder call.)

Owner amendment: approved; every Ceph OSD is also encrypted at rest with dm-crypt, keys in OpenBao (ADR-0061).

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- No reservation - desktops starve OSDs.
- Dedicated storage nodes - more hardware.

## Consequences

Positive:

- Storage stays responsive under load.

Negative:

- Slower recovery in business hours.

Follow-up work:

- Tune and test under the load gate.
