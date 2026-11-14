# ADR-0082: Provisioning webhook implementation choices

- Status: Proposed
- Date: 2026-11-14
- Decision ID: D81
- Related controls: AC-2, AC-2(1), AC-6, IA-4, SI-10, AU-2

## Context

ADR-0019, 0020, ADR-0051 and 0052 set the design (webhook, hardening, limited Keycloak client, immutable UID). The build tickets (#119-#122, #306) made the choices below. ADR-0062 (SCIM subset) already holds the payload shape, so this ADR is numbered 0082.

## Decision

- **Caller auth.** The DMZ HAProxy forwards the client cert in `Client-Cert` (ADR-0050). Styx pins the SHA-256 fingerprint of the DER cert against `PROVISION_CLIENT_CERT_FINGERPRINTS` (comma-separated) and also requires the `PROVISION_BEARER_TOKEN`. Both compare in constant time. Wrong `Host` (not `PROVISION_HOST`) returns 404. Rejections return only a short code (`cert_missing`, `cert_invalid`, `cert_not_allowed`, `bearer_missing`, `bearer_invalid`); no token or fingerprint is logged.
- **Idempotency storage.** The `Idempotency-Key` header (max 128 chars, required) is stored in `approved_requests.idempotency_key` with a `body_hash` of the payload. Same key and same hash replays the stored result (`Idempotent-Replay: true`); same key and a different hash is `IDEMPOTENCY_CONFLICT`. A replay of a `failed` request retries provisioning. `approval_id` and `external_id` are unique, so a reused approval or existing user returns 409 even with a new key.
- **Admin groups denied.** Groups in `KEYCLOAK_ADMIN_GROUPS` are refused with 403 `GROUP_NOT_ALLOWED`. The Keycloak client refuses them too (defence in depth). The approver must be a manager of every requested group (`PROVISION_GROUP_MANAGERS`), else 403 `APPROVER_UNKNOWN`.
- **Resumable provisioning.** Progress (`kc_user_id`, `username`, applied groups) is kept in `approved_requests.subject`, so a retry after a Keycloak failure resumes and never duplicates the user.
- **UID range.** `POSIX_UID_MIN` defaults to 100000. A new user gets max(ever allocated)+1, never lower than the minimum. Rows are append-only in `posix_uids`; a unique constraint on uid and user key makes concurrent allocation retry. UIDs are never reused or changed (ADR-0052).
- **Card binding.** At first login the card claims must match the approved request by exact key: EDIPI for CAC, certificate email (case-insensitive) for PIV/PIV-I. No match, a partial match, a name-only match or several matches go to the admin review queue (`card_reviews`). An admin approves (naming the request) or rejects. EDIPI and card UUID are never logged or put in audit detail.
- **Audit.** Every outcome writes an audit event: `provision.request.accepted`, `.replay`, `.denied`, `.conflict`, plus `card.bound`, `card.review.queued`, `card.review.bound`, `card.review.approved/rejected`.

## Alternatives considered

- Trust the HAProxy-verified cert alone: rejected, a second factor (bearer) limits a stolen-cert or misrouted-request case.
- Idempotency in memory or Redis: rejected, it must survive restarts and replicas; the database already holds the request.
- Auto-bind on name match: rejected, names are not unique keys (ADR-0016).
- Reuse UIDs of deleted users: rejected, would give a new person old file ownership.

## Consequences

- Rotating the cert or token needs a config change on both sides ([runbook](../runbooks/provisioning-webhook.md)).
- The review queue needs an admin to look at it; see the runbook.
- The Keycloak client permissions are documented in [keycloak-admin-client.md](../keycloak-admin-client.md).
