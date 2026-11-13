# Offboarding and access review runbook

Controls: AC-2, AC-2(3), AC-2(4), PS-4. Decisions: ADR-0022, 0023, 0024, 0071.
All calls need an admin session cookie (and CSRF header on writes) unless noted; `$P` is the portal origin.

## Remove access (immediate)

Disables the account in Styx (sessions killed, instances stopped, home frozen) and in Keycloak.

```
POST $P/api/users/{user_id}/remove-access
```

- 200: done. 502: Styx disabled but Keycloak failed; retry the call or disable in Keycloak.
- You cannot remove your own access. `PATCH /api/users/{user_id}/disable` is the Styx-only variant.

## End date

Set by the approved provisioning request (`endDate` in the enterprise extension of `POST /api/provision/requests`, ADR-0062). The lifecycle loop disables the account once `end_date` has passed (`disabled_reason=end_date`). To change it, resubmit through the approval workflow; there is no admin edit.

## Inactivity and auto-suspend

- **Inactivity:** accounts with no login for `LIFECYCLE_INACTIVITY_DAYS` (default 35) are disabled (`disabled_reason=inactivity`). Age counts from `last_login`, else `created_at`. Admins are exempt.
- **Unreviewed new accounts:** auto-suspended after 2 business days (Mon-Fri) without review (`disabled_reason=unreviewed`).

Daily review by the security officer:

```
GET  $P/api/admin/provisioned?days=14      # recently provisioned
GET  $P/api/admin/provisioned/digest       # digest text
POST $P/api/admin/provisioned/{user_id}/review
POST $P/api/admin/provisioned/{user_id}/suspend
```

The digest is also posted to `MATRIX_DIGEST_WEBHOOK_URL` (skipped when unset). Both loops run on the leader only.

To restore a wrongly disabled account, re-enable it in Keycloak and Styx before the 90-day deletion.

## Delete after 90 days

`ACCOUNT_DELETION_RETENTION_DAYS` (default 90) after `disabled_at`, the leader-only loop deletes homes, the Keycloak user and the Styx user. 404s count as done and the loop is idempotent. Manual early delete (fails with 409 while the user owns instances or templates):

```
DELETE $P/api/users/{user_id}
```

## Quarterly access review

Group managers (`Group.manager_user_id`) and admins review each quarter, e.g. `2026-Q4`.

```
GET  $P/api/access-review?quarter=2026-Q4
POST $P/api/access-review/decisions
     {"group_id": "...", "user_id": "...", "quarter": "2026-Q4", "decision": "certify"|"revoke"}
GET  $P/api/access-review/export.csv?quarter=2026-Q4
```

- One decision per group, user and quarter; a repeat returns 409.
- `revoke` removes the group membership and the Keycloak group membership.
- Keep the CSV as the evidence for the quarter. Columns: quarter, group, username, email, decision, actor, decided_at.

## Audit events

`account.disabled`, `user.remove_access`, `user.remove_access_kc_failed`, `user.delete`, `account.reviewed`, `access_review.certify`, `access_review.revoke`.
