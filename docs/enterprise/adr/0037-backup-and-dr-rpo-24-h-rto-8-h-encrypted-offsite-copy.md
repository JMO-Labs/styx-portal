# ADR-0037: Backup and DR: RPO 24 h, RTO 8 h; encrypted offsite copy

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D37
- Related controls: CP-9, CP-10, CP-6, CP-7, SC-28

## Context

Moderate impact systems normally expect tested backup and recovery; the design has a single site.

Source: docs/enterprise/design.md section 5.

## Decision

Target RPO 24 h and RTO 8 h using CNPG backups, Velero and nightly home snapshots. Offsite copy is an encrypted export to a CUI-authorized cloud bucket (~$20-50/month, accepted), using CephFS snapshot-based incremental export. A full-site restore test is part of phase 1. No second site: CP-7 is a recorded exception (R03).

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Warm second site - cost and scope.
- Local-only backups - no site-loss protection.

## Consequences

Positive:

- Documented recovery objectives; offsite copy.

Negative:

- No alternate processing site (CP-7); risk acceptance R03.
- Recovery within 8 h is unproven until the phase 1 restore test.
- Recurring cloud cost.
- SC-13 gap: the offsite copy uses Kopia (AES256-GCM-HMAC-SHA256 or CHACHA20-POLY1305-HMAC-SHA256). The algorithms are approved, but Kopia is not a FIPS-validated module, and its password KDF is scrypt (the only KDF Kopia supports). This stays open debt under the R05 waiver (ADR-0011).

Implementation:

- The offsite export tool is Kopia (chosen over restic, rclone crypt, Velero and Ceph-native mirroring because only Kopia makes the cipher configurable and manages S3 Object Lock itself). It ships as the opt-in component `deploy/k8s/offsite-export/` (issue #13): a nightly export of CephFS subvolume snapshots to one client-side-encrypted repository in an Object Lock bucket, a daily verify, alerts for failure and RPO breach, and keys from OpenBao (ADR-0042) with offline escrow. IaC done, not deployed. See docs/operate/offsite-backup.md.

Follow-up work:

- Full-site restore test (phase 1 exit); record CP-6/CP-7 in eMASS.
- Full-site restore runbook: [runbooks/full-site-restore.md](../runbooks/full-site-restore.md), applying A1 (offsite scope), B1 (two escrow sets) and D1 (RTO clock) from #14.
