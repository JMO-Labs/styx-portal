# ADR-0071: Wiki.js and Matrix implementation choices

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D70
- Related controls: IA-2, AC-2, AU-6, IR-4, CP-9, SC-7
- Refines: ADR-0043, ADR-0059

## Context

ADR-0043 chose Wiki.js and Matrix (Synapse plus Element) with OIDC to Keycloak. The deployment issues (#275-#281) left choices no earlier ADR fixes. This records them for owner acceptance.

## Decision

1. **OIDC-only login.** Wiki.js and Synapse authenticate only against the Keycloak realm `styx`. Wiki.js has its Local strategy disabled and the bootstrap admin removed after first login. Synapse sets `enable_registration: false` and has no local password login. Smart-card login (ADR-0015) therefore covers both.
2. **CNPG databases.** Each app gets its own CNPG cluster in its own namespace (`wikijs-db`, `synapse-db`), with a daily `ScheduledBackup` and an offsite object store. Credentials come from OpenBao through External Secrets (ADR-0042).
3. **Matrix room adapter, config-gated.** The backend posts notifications to one Matrix room through `backend/app/services/notify_matrix.py`. It is on only when `MATRIX_NOTIFY_HOMESERVER`, `MATRIX_NOTIFY_ROOM_ID` and `MATRIX_NOTIFY_TOKEN` are all set; otherwise it does nothing. It never raises and never logs the token. The values come from the optional secret `styx-matrix-notify`.
4. **SMTP stays optional (ADR-0059).** Neither Synapse nor Wiki.js requires a mail relay. Without SMTP there are no email notifications or password resets; the portal and Matrix room carry alerts.
5. **Federation disabled.** Synapse sets `federation_domain_whitelist: []` and `allow_public_rooms_over_federation: false`. The namespace network policy is default deny with only the flows each app needs, so no remote homeserver is reachable.
6. **Service seeding.** On the enterprise profile `backend/app/services/enterprise_services.py` seeds "My services" rows for Wiki.js and Element from `WIKI_URL` and `ELEMENT_URL`. An empty URL seeds nothing.

## Alternatives considered

- Local accounts as break-glass: a second login path outside the smart-card flow.
- Shared CNPG cluster for both apps: one failure domain and shared credentials.
- Require SMTP: blocks on an unknown org service (ADR-0059).
- Federated Matrix: widens the boundary for no stated need.

## Consequences

Positive:

- One authentication path; no local credentials to review.
- A Wiki.js or Synapse database problem stays inside its own namespace.
- Notifications work without SMTP, and the adapter is inert until configured.

Negative:

- Wiki.js 2 keeps authentication strategies in its database, so the OIDC bootstrap is a manual step (see the runbook).
- The notification bot token is a long-lived secret that an operator must create and rotate by hand.

Follow-up work:

- Owner acceptance of this ADR.
- Runbook: [wikijs-matrix.md](../runbooks/wikijs-matrix.md).
