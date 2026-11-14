# Provisioning webhook runbook

Controls: AC-2, AC-2(1), IA-4, SI-10, AU-2. Decisions: ADR-0019, 0020, 0062, 0082.
`$P` is the portal origin. Admin calls need an admin session cookie (and CSRF header on writes).

## Rotate the bearer token

1. Generate a new token: `openssl rand -base64 48`.
2. Store it in OpenBao and update the Power Automate connection with the same value. Never paste it in tickets or chat.
3. External Secrets syncs `PROVISION_BEARER_TOKEN`; restart the backend so it reads the new value.
4. Send a test request from Power Automate. `401 bearer_invalid` means the two sides differ.

There is a short gap between steps 2 and 3. Schedule it outside approval hours, and let Power Automate retry (requests are idempotent by `Idempotency-Key`).

## Rotate the client certificate

Styx pins the SHA-256 fingerprint of the DER cert.

1. Get the new fingerprint: `openssl x509 -in new.pem -outform DER | openssl dgst -sha256`.
2. Set `PROVISION_CLIENT_CERT_FINGERPRINTS` to `<old>,<new>` (comma-separated, lowercase hex) and restart the backend.
3. Install the new cert in Power Automate and the DMZ HAProxy CA trust if the issuer changed ([dmz-haproxy.md](dmz-haproxy.md)).
4. Send a test request. Then remove the old fingerprint and restart.

## Work the card review queue

Cards that do not match an approved request exactly are queued (`card.review.queued`). The user cannot sign in until an admin resolves it. Check the queue daily.

```
GET  $P/api/admin/card-reviews?status=pending
POST $P/api/admin/card-reviews/{id}/resolve
     {"decision": "approve", "request_id": "<approved request id>"}
     {"decision": "reject"}
```

- The list shows card type and reason (`no_match`, `multiple_matches`, `invalid_claims`), not the EDIPI or card UUID.
- Confirm identity out of band (the approver or the user's manager) before approving. Pick the approved request in `pending_binding` that belongs to this person.
- `approve` binds the card and audits `card.review.bound`. `reject` leaves the request waiting. 409 means already resolved or the request is not awaiting binding.

## Troubleshooting

| Response | Meaning |
|---|---|
| 404 `bad_host` | Request did not use `PROVISION_HOST` |
| 401 `cert_missing`, `cert_invalid` | HAProxy did not forward a valid `Client-Cert` |
| 401 `cert_not_allowed` | Fingerprint not in `PROVISION_CLIENT_CERT_FINGERPRINTS` |
| 401 `bearer_missing`, `bearer_invalid` | Wrong or missing token |
| 403 `GROUP_NOT_ALLOWED` | Request names an admin group |
| 403 `APPROVER_UNKNOWN` | Approver is not a manager of every group |
| 409 `IDEMPOTENCY_CONFLICT` | Same key, different body |
| 409 `APPROVAL_REUSED`, `USER_EXISTS` | Approval or user already provisioned |
| Request `failed` | Keycloak call failed; resend with the same key to retry |

Rejections are logged by code only; look up the audit events `provision.request.*` for the rest.
