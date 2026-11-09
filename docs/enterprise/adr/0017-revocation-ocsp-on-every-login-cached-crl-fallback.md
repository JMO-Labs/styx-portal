# ADR-0017: Revocation: OCSP on every login, cached CRL fallback

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D17
- Related controls: IA-5(2), SC-17, IA-2(12)

## Context

DoD PKI practice relies on revocation checking for certificate-based login.

Source: docs/enterprise/design.md section 5.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1).

## Decision

Check OCSP (per issuer) first and fall back to a local CRL mirror maintained by a cronjob and read by path in Keycloak. Alert on CRL age. (Builder call.)

Owner amendment: fail closed. If OCSP fails and the CRL mirror is past its nextUpdate, login is refused and an alert fires. Break-glass accounts (ADR-0025) are excepted.

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- CRL only - staleness window.
- No revocation checking - unacceptable for smart cards.
- Per-login CRL download - slow and fragile.

## Consequences

Positive:

- Timely revocation; resilient to OCSP outage.

Negative:

- Dependence on DoD and federal OCSP reachability from Keycloak.
- CRL mirror has a bounded staleness risk, covered by the age alert.

Follow-up work:

- Set CRL max-age and failure policy in phase 2.
