# ADR-0011: No FIPS or STIG engineering; exceptions recorded

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D11
- Related controls: CM-6, SC-13, SA-4

## Context

The owner states exceptions for FIPS-validated crypto and STIG baselines have been obtained; Ubuntu is acceptable.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Do not engineer for FIPS-validated modules or STIG compliance. Record the exceptions with the ATO package.

Owner amendment (R05): accepted on condition that the FIPS/STIG exception references (issuer, date, scope) are attached in eMASS and cited here before Phase 1 starts. Exception references: TODO (owner): issuer, date, scope - required before Phase 1 starts.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- FIPS-validated crypto modules - not required per owner.
- STIG-hardened OS - not required per owner.

## Consequences

Positive:

- Lower engineering cost and wider component choice.

Negative:

- Exceptions must be documented against SC-13 and CM-6; approval could be withdrawn.
- Cryptography choices cannot be claimed as FIPS-validated.

Follow-up work:

- Attach exception references in control matrix; confirm evidence with the owner.
