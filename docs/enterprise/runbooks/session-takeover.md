# Session takeover runbook

Controls: AC-17, AU-2, AU-6, AU-12. Decisions: ADR-0060, ADR-0075. `$P` is the portal origin.

Who: `platform-admin` and `help-desk` can take over. `platform-admin` and `auditor` (the security officer) review. Roles come from Keycloak realm roles and apply at the next login.

## Take over

1. Sign in with your staff account. Open the session in the portal system view and choose Take over.
2. Pick the mode: **View** opens the Selkies `#shared` (view-only) client; **Control** opens the normal client.
3. Enter the ticket number or reason. It is required; an empty reason is rejected.
4. The user sees a persistent banner naming you and the mode. The security officer gets a Matrix alert if `MATRIX_SECURITY_WEBHOOK_URL` is set.

API: `POST $P/api/instances/<id>/takeover` with `{"mode":"view|control","reason":"..."}`. 409 means another takeover is active; 403 means your role does not allow it (logged as `takeover.denied`).

Without an active takeover, the instance URL returns the no-access page for everyone but the owner, admins included.

## End

Choose End takeover in the portal, or `DELETE $P/api/instances/<id>/takeover` (204). End every takeover when done: the access stops and the banner clears. A 404 means none is active.

## Monthly review

Security officer or auditor, in the first week of each month:

1. Download the previous month: `GET $P/api/admin/takeovers/report?month=YYYY-MM` (CSV `takeovers-YYYY-MM.csv`). The download is itself audited.
2. Check every row: actor, user, a real ticket or reason, sensible mode and duration. A row with an empty end was never closed; end it and ask the actor why.
3. Cross-check against Elastic (`event.dataset=styx.audit`, `takeover.*`) and the Matrix alerts. Missing alerts point at the webhook, not at missing takeovers.
4. Record the review result (reviewer, month, findings) in the usual review evidence.

Live list: `GET $P/api/admin/takeovers?since=<ISO time>`.

## Troubleshooting

- No alert in Matrix: check `MATRIX_SECURITY_WEBHOOK_URL` and backend logs for `takeover alert failed`. The takeover still happened.
- Staff user gets 403: check their Keycloak realm role, then have them log in again.
