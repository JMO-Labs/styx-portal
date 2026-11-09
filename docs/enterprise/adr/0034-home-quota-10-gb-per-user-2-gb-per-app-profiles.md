# ADR-0034: Home quota 10 GB per user; 2 GB per-app profiles

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D34
- Related controls: SC-5, SC-28, CM-12

## Context

Storage is limited and conservative defaults are preferred.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Give each user a 10 GB home (warn at 80%) mounted in every desktop, and 2 GB persistent profiles per app as CephFS subvolumes (ADR-0054). Homes are keyed by an immutable POSIX UID (ADR-0052).

Owner amendment: a departed user's home is frozen read-only at disable. The group manager may request a handoff during the 90 days before deletion (ADR-0022). The home is then deleted with the account.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Unlimited homes - exhausts capacity.
- Ephemeral-only desktops - loses user data.

## Consequences

Positive:

- Bounded storage growth.

Negative:

- Users with larger data needs must use OneDrive or request overrides.

Follow-up work:

- Self-service quota view in phase 5.
