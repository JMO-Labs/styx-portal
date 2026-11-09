# ADR-0038: DLP defaults with per-group override

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D38
- Related controls: AC-4, SC-7, AU-2, AU-12, MP-7

## Context

CUI must not leave through unlogged channels.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Allow clipboard text both ways; allow file upload in; disable download out and local printing; apply user+time watermark. Clipboard and file events are logged as metadata only (user, time, direction, size, type, filename hash), never content. Elastic is not a CUI store. Groups may override.

Owner amendment: any per-group DLP override needs written approval from the security officer and is recorded.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Block clipboard entirely - usability cost.
- Log clipboard content - would make Elastic a CUI store.
- No logging of clipboard - violates anti-goal.

## Consequences

Positive:

- Controls and evidence for CUI handling.

Negative:

- Clipboard text both ways remains an exfiltration path, mitigated by metadata logging and watermark.
- Metadata cannot show what was copied; investigation relies on correlation.

Follow-up work:

- Event schema and enforcement points in phase 4.
