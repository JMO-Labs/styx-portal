# ADR-0075: Session takeover implementation choices

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D74
- Related controls: AC-17, AU-2, AU-6, AU-12
- Refines: ADR-0060, ADR-0026

## Context

ADR-0060 fixed the takeover policy (no consent, banner, reason, alert, monthly review). The implementation left choices that no earlier ADR records. This records them for owner acceptance.

## Decision

1. **`staff_role` comes from Keycloak realm roles.** On each federated login `sync_staff_role` (`backend/app/services/federation.py`) reads the realm-role claim (default `realm_roles`, overridable by `staff_role_claim`). The highest match of `platform-admin`, `help-desk`, `auditor`, `group-manager` wins; no match clears it. `User.role == "admin"` counts as `platform-admin`. Only `platform-admin` and `help-desk` pass `can_takeover`.
2. **Enterprise forwardAuth requires an active takeover for non-owners.** With `STYX_PROFILE=enterprise`, `auth-check` (`routers/instance_auth.py`) lets through the instance owner, or the actor of that instance's active (not ended) takeover. Everyone else, admins included, gets the no-access page. The homelab profile keeps owner-or-admin.
3. **One active takeover per instance.** A partial unique index backs a 409 on a second start. `reason` is mandatory and trimmed. Denied attempts write `takeover.denied`.
4. **View is the Selkies `#shared` client.** The portal opens `/desktop/<sub>#shared` for view mode. The agent gateway treats `role=viewer` as shared: it does not take the seat or hold the lock. Control opens the normal client.
5. **The security officer is `platform-admin` or `auditor`.** They list takeovers (`GET /api/admin/takeovers`) and download the report. `help-desk` can take over but cannot read the review data.
6. **Alert is a Matrix webhook.** On start, `takeover_alert.notify_start` posts plain text (actor id, user id, mode, reason, time) to `MATRIX_SECURITY_WEBHOOK_URL`. Unset means skipped. A failed post is logged and never blocks the takeover.
7. **Monthly report is CSV.** `GET /api/admin/takeovers/report?month=YYYY-MM` returns `takeovers-YYYY-MM.csv` with actor, user, instance, mode, reason, start, end, duration. Cells starting with `= + - @` are prefixed with `'`. Each download is audited as `takeover.report`.
8. **Audit events.** `takeover.start`, `takeover.end`, `takeover.denied`, `takeover.report`, shipped with the other `styx.audit` events.

## Alternatives considered

- Role from a Styx-side admin screen: a second source of truth next to Keycloak (ADR-0051).
- Letting admins through forwardAuth always: bypasses the logged, reasoned takeover.
- Email or portal-only alert: Matrix is already used for the digest (ADR-0073).
- XLSX or PDF report: CSV is enough for the review and easy to diff.

## Consequences

Positive: every non-owner session access has a reason, a banner and an audit row; the monthly review needs no extra tooling.

Negative: a Keycloak role change applies only at the user's next login; the alert is best-effort, so the monthly review is the backstop.
