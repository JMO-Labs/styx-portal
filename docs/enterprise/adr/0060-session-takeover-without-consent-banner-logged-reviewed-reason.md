# ADR-0060: Session takeover without consent, with banner and logged, reviewed reason

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-11-09
- Decision ID: D45a
- Supersedes: ADR-0045
- Related controls: AC-17, AC-6, AU-2, AU-3, AU-6, AU-12

## Context

ADR-0045 required user consent before help desk could view a session and a second consent to take control. Users are not always available to consent, which blocks support. The owner chose consent-free takeover limited to support roles, made visible to the user and held accountable through logging and review.

Amendment source: Owner approval Rounds 1-5, 2026-11-09 (issue #1). Supersedes ADR-0045.

## Decision

- Only platform admin and help desk (ADR-0026 roles) may view or take control of a user's desktop session, without the user's consent. Auditors and group managers may not view or take control of sessions.
- For the whole takeover the user sees a persistent banner naming who is viewing or controlling the session.
- A ticket number or reason is required before a takeover starts.
- Each takeover is logged to Elastic with actor, user, start, end, mode (view or control) and reason.
- Each takeover alerts the security officer.
- The security officer or the auditor reviews takeovers monthly.

Session sharing (peer collaboration) stays a v2 non-goal and is not covered here. The mechanism lives in the Styx gateway, as planned for ADR-0045.

## Alternatives considered

- Consent-based shadowing (ADR-0045) - superseded; users may be unavailable to consent.
- Silent admin viewing - no user visibility or accountability.

## Consequences

Positive:

- Support is not blocked by an unavailable user.
- Every takeover is visible to the user, attributable, alerted and reviewed.

Negative:

- Users lose the right to refuse viewing; the banner, logging and monthly review are the compensating controls.
- The monthly review is a recurring duty for the security officer or auditor.

Follow-up work:

- Gateway takeover mechanism, banner and Elastic event in phase 5.
