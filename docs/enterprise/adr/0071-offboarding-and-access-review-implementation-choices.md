# ADR-0071: Offboarding and access-review implementation choices

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D70
- Related controls: AC-2, AC-2(3), AC-2(4), PS-4
- Refines: ADR-0022, ADR-0023, ADR-0024

## Context

The offboarding, new-account review and quarterly access-review issues left choices that no earlier ADR fixes. This records them for owner acceptance. (The ticket proposed number 0062; that is taken by the SCIM ADR, so this is the next free number.)

## Decision

1. **Business days are Monday to Friday.** `business_days_between` in `backend/app/services/new_account_review.py` skips Saturday and Sunday only. There is no holiday calendar. A new account unreviewed for more than 2 business days is auto-suspended (`disabled_reason=unreviewed`); the hourly pass is idempotent.
2. **Inactivity is measured from `last_login`, else `created_at`.** An account that never logged in ages from creation. `LIFECYCLE_INACTIVITY_DAYS` (default 35) sets the cut-off. Admins are exempt from the inactivity rule but not from `end_date`. `end_date` (from the provisioning webhook `endDate`) disables on or after that instant (`backend/app/services/lifecycle_jobs.py`).
3. **Group manager is `Group.manager_user_id`.** A manager reviews only the groups that point at them; admins see every group. There is no delegation or deputy.
4. **Digest goes to a Matrix webhook URL.** `MATRIX_DIGEST_WEBHOOK_URL` receives the daily new-account digest (`services/new_account_digest.py`). Unset means the digest is skipped. The same text is available at `GET /api/admin/provisioned/digest`.
5. **One disable path.** Every flow (remove access, end date, inactivity, unreviewed, suspend) calls `disable_account`: it sets `disabled_at` and `disabled_reason`, bumps `token_version`, revokes refresh tokens, stops live instances and freezes the home. Keycloak is disabled afterwards; a Keycloak failure never undoes the local disable.
6. **Delete after 90 days.** `ACCOUNT_DELETION_RETENTION_DAYS` (default 90) after `disabled_at`, the leader-only `account_deletion` loop removes homes, the Keycloak user and the Styx user.
7. **Access review decisions are final per quarter.** One `certify` or `revoke` per group, user and quarter (409 on repeat). Revoke removes the group link and, when the group has a `kc_group_id`, the Keycloak membership. CSV export neutralises spreadsheet formulas.

## Alternatives considered

- Holiday calendar for business days: more configuration, no assessor requirement.
- Inactivity from Keycloak last-auth: adds a dependency on Keycloak availability.
- Editable review decisions: weaker evidence.

## Consequences

Positive: one auditable disable path; evidence is in the audit log and the CSV.

Negative: public holidays count as business days, so suspension can come earlier than staff expect.
