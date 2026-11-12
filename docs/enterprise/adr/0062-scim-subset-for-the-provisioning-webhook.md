# ADR-0062: SCIM subset for the provisioning webhook

- Status: Proposed
- Date: 2026-11-12
- Decision ID: D61
- Related controls: AC-2, AC-2(1), IA-4, SI-10, AU-2, AU-3
- Refines: ADR-0019 (D19), ADR-0020 (D20), ADR-0021 (D21)

## Context

D19 says Power Automate calls a "SCIM-shaped" HTTPS webhook; design.md section 7 left the subset open. Power Automate's HTTP connector sends plain JSON, so full SCIM (discovery, filtering, bulk) buys nothing. The subset below is what Styx accepts; everything else is rejected. Hardening (mTLS, bearer token, IP allowlist) is ADR-0020 and not repeated here.

The machine-readable contract is `docs/enterprise/schemas/scim-provisioning-v1.schema.json` (JSON Schema 2020-12). The ADR is normative for semantics; the schema for shape.

## Decision

Base path `/scim/v2` on the provision host (ADR-0049). Content type `application/scim+json` (plain `application/json` also accepted). Unknown properties are rejected (strict schema, D20).

## Operations

Only the `User` resource is supported. No Groups, Bulk, search, `/Schemas`, `/ServiceProviderConfig` or filter endpoints.

| Operation | Request | Effect |
|---|---|---|
| Create | `POST /scim/v2/Users` | Creates a Keycloak user (D51 client) and group memberships. Returns 201 |
| Update | `PATCH /scim/v2/Users/{id}` | `replace` of `groups` or `endDate` only. Returns 200 |
| Disable | `PATCH /scim/v2/Users/{id}` | `replace` of `active` with `false`. Kills sessions (D22). Returns 200 |

- There is no delete: `DELETE` returns 405. Deletion is the D22 retention job (90 days after disable) and nothing else.
- There is no re-enable: `active: true` on PATCH is rejected (`UNSUPPORTED_OPERATION`). Returning staff need a new approved request, which the D23 review sees.
- `PUT` is not supported (405). Only `replace` ops are accepted; `add` and `remove` are rejected.
- `{id}` is the Styx user id returned by create. Power Automate stores it, or looks it up with `GET /scim/v2/Users?externalId=<id>` (the only supported query, exact match, returns 0 or 1 result).
- Only non-admin groups may be named (D20, D51). Any group the Styx client cannot manage returns `GROUP_NOT_ALLOWED`.

## Attributes

Mapping from D21 form fields to the create body:

| D21 form field | SCIM attribute | Rules |
|---|---|---|
| First name | `name.givenName` | 1-64 chars |
| Last name | `name.familyName` | 1-64 chars. Username `first.last` is derived by Styx (ADR-0016); `userName` is accepted and ignored |
| Email | `emails[0].value` | exactly one; used for PIV/PIV-I first-login binding (ADR-0016) |
| Card type (CAC/PIV/PIV-I) | `urn:styx:scim:schemas:provisioning:1.0:Request.cardType` | enum `CAC`, `PIV`, `PIV-I` |
| EDIPI (CAC only) | `...Request.edipi` | 10 digits; required for CAC, forbidden otherwise |
| Groups | `...Request.groups` | 1-20 unique group slugs |
| Approving manager | `...Request.approverEmail` | must be a known group manager of every requested group (D20) |
| End date (required for contractors) | `...Request.endDate` and `personType` | `personType` is `employee` or `contractor`; contractor requires `endDate` (ISO date, in the future) |
| (approval, not a form field) | `...Request.approvalId` | see Approval ID |
| (request identity) | `externalId` | Forms response ID, <= 128 chars |

`active` must be `true` on create. Name, email, card type and EDIPI are immutable after create (ADR-0016): a change is a help-desk action, not a webhook one (`IMMUTABLE_ATTRIBUTE`). Update paths are limited to `...Request:groups` and `...Request:endDate`; a PATCH carries up to 3 operations and the extension object with its own `approvalId`.

## Idempotency

- Every POST and PATCH carries `Idempotency-Key` (1-128 chars, from Power Automate `workflow().run.name` plus action name). Missing key: 400 `IDEMPOTENCY_KEY_MISSING`.
- Styx stores key, SHA-256 of the canonical body, status and response for 7 days (keys are unique per operation and target).
- Same key and same body: the stored response is returned with the original status and header `Idempotent-Replay: true`; no side effects; audited as outcome `replay`.
- Same key and different body: 409 `IDEMPOTENCY_CONFLICT`; nothing is changed.
- Retries after a 5xx or timeout reuse the key, so a network failure never produces a second account.
- Create is also naturally unique on `externalId`: a new key with an existing `externalId` returns 409 `USER_EXISTS` (scimType `uniqueness`).

## Approval ID

- `approvalId` is the Power Automate approval run ID (UUID). Every create and every update/disable PATCH must carry one.
- It is single-purpose: an approval ID is bound on first use to one `externalId` and one operation type. Reuse for another request or operation returns 409 `APPROVAL_REUSED`. Re-sending the identical call with the same idempotency key is a replay, not reuse.
- Styx validates format, uniqueness and that `approverEmail` is a known group manager for each group (`APPROVER_UNKNOWN` otherwise). It cannot verify the M365 approval itself (D20, R04); the D23 human review is the real control. The stored approval ID gives that reviewer the join key back to the Power Automate run history.
- Disable PATCH may carry an approval ID from the "Remove access" flow; the same rules apply.

## Error model

Responses use the RFC 7644 section 3.12 error envelope plus `styxCode`; `detail` is generic and never echoes request values (no PII in errors). Defined as `$defs/error`.

| HTTP | scimType | styxCode | When |
|---|---|---|---|
| 400 | invalidSyntax | `SCHEMA_INVALID`, `IDEMPOTENCY_KEY_MISSING` | not JSON, unknown property, bad type |
| 401 | | `UNAUTHENTICATED` | missing or expired bearer token |
| 403 | | `CLIENT_CERT_REJECTED`, `IP_NOT_ALLOWED`, `GROUP_NOT_ALLOWED`, `APPROVER_UNKNOWN` | transport or authorization control failed |
| 404 | noTarget | `USER_NOT_FOUND` | PATCH target unknown |
| 405 | | `UNSUPPORTED_OPERATION` | DELETE, PUT, other resources |
| 409 | uniqueness | `USER_EXISTS`, `APPROVAL_REUSED`, `IDEMPOTENCY_CONFLICT` | state conflict |
| 422 | invalidValue, mutability | `SCHEMA_INVALID`, `IMMUTABLE_ATTRIBUTE`, `UNSUPPORTED_OPERATION` | well-formed but semantically invalid (EDIPI on PIV, contractor without end date, past end date, `active: true`) |
| 429 | | `RATE_LIMITED` | per-client limit; `Retry-After` header and `retryAfterSeconds` |
| 500/503 | | `INTERNAL`, `UPSTREAM_UNAVAILABLE` | Keycloak or database failure; safe to retry with the same idempotency key |

Failures that precede identification of the caller (mTLS or bearer) return the same envelope with no detail beyond the code. Creates are atomic from the caller's view: if Keycloak succeeds but the database write fails, the retry resolves by `externalId` and completes instead of returning 409.

## Audit event

One event per call, accepted or rejected, defined as `$defs/auditEvent` and shipped to Elastic with the other audit logs (AU-2, AU-3, AU-12).

- Fields: `event` (`provision.user.create|update|disable`, `provision.rejected`), `timestamp` (UTC), `requestId`, `idempotencyKey`, `approvalId`, `approver`, `clientCertFingerprint` (SHA-256), `sourceIp`, `outcome` (`success|replay|rejected|error`), `httpStatus`, `styxCode`, `resource` (`type`, `externalId`, `keycloakId`, `username`) and `changes` (attribute names only).
- No name, email, EDIPI or card id of the subject is logged; the Styx `username` and `keycloakId` identify the account. Request bodies are never logged.
- Create events also feed the D23 "Recently provisioned" view.

## Alternatives considered

- Implement full SCIM 2.0 - Power Automate would not use discovery, filters or bulk; larger attack surface on the only door in.
- A bespoke non-SCIM JSON API - loses the option of a standard IdP connector later.
- Allow DELETE - D22 retention is the single deletion path and keeps the 90-day review (D22).
- Allow re-enable by PATCH - would bypass the fresh approval and D23 review.

## Consequences

Positive:

- Small, strictly validated surface; schema is testable and shareable with the flow author.
- Retries are safe; every approval is traceable to a flow run.

Negative:

- Not a conformant SCIM server; a generic SCIM client will not work unchanged.
- Approval ID is a join key, not proof (R04).
- Rehire needs a new request.

Follow-up work:

- Implement the endpoint and validate bodies against the schema in phase 2 (no code in this ADR).
- Owner acceptance of this ADR (Status Proposed).
- Form data retention rules remain with ADR-0021.
