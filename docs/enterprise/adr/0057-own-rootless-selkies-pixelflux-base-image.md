# ADR-0057: Own rootless Selkies and pixelflux base image

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D57
- Related controls: CM-2, CM-6, SA-10, SR-3

## Context

Third-party desktop base images (linuxserver.io) add provenance and privilege questions.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Build an own rootless Selkies plus pixelflux Ubuntu base image. The desktop namespace carries a documented Pod Security Admission exception. (Builder call.)

Owner amendment: the desktop namespace Pod Security Admission exception is recorded in control-matrix.md (CM-6/CM-7). Each Selkies patch is offered upstream before it is kept locally.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- linuxserver.io images - external provenance, root init.

## Consequences

Positive:

- Owned, signed, minimal base.

Negative:

- PSA exception must be justified in the SSP; maintenance burden.

Follow-up work:

- Document the exception in the control matrix in phase 3.
