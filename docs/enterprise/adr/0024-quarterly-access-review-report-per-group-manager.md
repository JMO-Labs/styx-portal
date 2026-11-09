# ADR-0024: Quarterly access-review report per group manager

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D24
- Related controls: AC-2, AC-2(3), AC-6

## Context

Periodic recertification of access is required for Moderate systems.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Generate a quarterly access-review report per group manager in the admin console, with certify and revoke actions and a CSV export. Admin CSV import must reference an approval record. (Builder call on format.)

Owner amendment (R04): the security officer is the named owner of the daily review of new accounts (ADR-0023). New accounts left unreviewed for 2 business days are auto-suspended.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Annual review - too infrequent.
- Manual spreadsheets - error-prone.

## Consequences

Positive:

- Evidence of recertification with actions recorded.

Negative:

- Group managers must act on reports.

Follow-up work:

- Sign-off workflow and report content in phase 2/5.
