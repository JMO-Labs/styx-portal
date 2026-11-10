# ADR-0050: DMZ proxy is an HAProxy pair forwarding the client cert

- Status: Accepted
- Accepted: 2026-11-09
- Date: 2026-10-28
- Decision ID: D50
- Related controls: SC-7, SC-8, SC-23, AC-17

## Context

The DMZ proxy terminates TLS; Keycloak must still see the client certificate to authenticate the card.

Source: docs/enterprise/design.md section 5.

## Decision

The DMZ proxy is a pair of HAProxy instances terminating TLS and forwarding the client certificate in a header format that Keycloak's x509 lookup SPI supports. Traefik runs in-cluster behind it. (Builder call; resolves the HAProxy-or-Traefik question in ADR-0012.)

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Traefik in the DMZ - less suited to header-based cert forwarding.
- TLS passthrough to Keycloak - loses DMZ inspection and rate limits.

## Consequences

Positive:

- Mature, well-understood DMZ component.

Negative:

- Header trust: only the proxy may set the cert header; Keycloak must reject it from elsewhere.

Follow-up work:

- Define header format, strip-and-set rules and network policy in phase 2.
- Header format and strip-and-set rules chosen (issue #7, [runbook](../runbooks/dmz-haproxy.md), contract in `deploy/enterprise/dmz-haproxy/README.md`). Format: Keycloak `haproxy` x509cert-lookup provider. `Client-Cert` = `%[ssl_c_der,base64]` (base64 DER leaf) and `Client-Cert-Chain` = `%[ssl_c_chain_der,base64]`. Rules: HAProxy always deletes client-supplied `Client-Cert`, `Client-Cert-Chain`, `X-Forwarded-*` and `Forwarded` first. It sets the two cert headers only on `login.<domain>` and only when `ssl_c_used` and `ssl_c_verify 0`. Login without a verified card gets a 403 page. SNI must equal Host on mTLS hosts (421). HAProxy re-encrypts to a dedicated Traefik entrypoint over mTLS. The Traefik entrypoint, Keycloak flags and Cilium policy (#19) are left to their own tickets.
