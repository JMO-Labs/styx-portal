# ADR-0079: Smart-card helper implementation

- Status: Proposed
- Date: 2026-11-13
- Decision ID: D78
- Related controls: IA-2(12), SC-12, SA-11
- Refines: ADR-0041

## Context

ADR-0041 chose an own open-source helper. This records how it was built (issue #197): module, transport, token, launch and error codes.

## Decision

1. **Go module `smartcard/`** (`github.com/JMO-Labs/styx-portal/smartcard`). Packages: `apdu` (shared allowlist), `relay` (in-desktop, bridges WSS to vpcd), `helper` (Windows client: PC/SC, CAC mTLS, confirm dialog), `cmd/styx-card-helper`, `cmd/styx-card-relay`. Tests: `smartcard/test.sh`.
2. **WSS transport via the `/smartcard` route.** The helper dials `wss://<host>/w/<sub>/smartcard`. Traefik routes it (priority 60, above the stream route) to the relay port in the desktop when `SMARTCARD_ENABLED` is set (`backend/app/services/route_writer.py`). The relay speaks the virtualsmartcard vicc protocol to the local vpcd (`127.0.0.1:35963`). One helper at a time; auth happens before upgrade and before any vpcd dial.
3. **Token: 120 s TTL, single use.** The owner (admins excluded) mints it with `POST /api/instances/{id}/smartcard-token`. Stored hashed, bound to user and instance. The relay redeems it via `POST /api/smartcard/redeem` with `X-Relay-Secret` (`SMARTCARD_RELAY_SECRET`; empty disables redeem) and the username from the helper's client certificate, which must match. Mint, redeem ok and redeem fail are audited.
4. **`styx-card://connect?host=<h>&token=<t>` launch.** The MSI registers the handler per machine. The helper accepts only that scheme and action, and only hosts that are a proper subdomain of `STYX_CARD_ALLOWED_DOMAINS`; anything else is rejected before dialing.
5. **Status words for refusals.** `6D00` (INS not supported): the APDU is not in `smartcard/apdu-allowlist.yaml`. `6982` (security status not satisfied): the user declined, or did not answer the 30 s confirm dialog, for a signing operation. Signing entries (`GENERAL AUTHENTICATE`) are marked `signing: true` and always prompt. Default is deny.
6. **Allowlist change is a reviewed code change.** See the runbook.

## Alternatives considered

- Redirect over the Selkies stream: no smart-card channel in Selkies, and it would mix with the media path.
- Multi-use or long-lived tokens: a leaked URL would give card access; one short use limits it.
- Prompt once per session: a compromised desktop could sign freely after the first yes.

## Consequences

Positive: card operations are limited to listed APDUs, signing needs a human yes, token theft has a short window.
Negative: Windows only for now (macOS later, ADR-0041). Every new APDU needs a code review and release.

## Dependencies and license policy

Checked against `docs/enterprise/license-policy.yaml` (allow list).

| Dependency | Version | License | Policy | Use |
|---|---|---|---|---|
| virtualsmartcard (vpcd) | 0.10 | GPL-3.0 | allow (GPL-3.0) | Built from a pinned, sha256-checked tarball in `images/enterprise-base/Dockerfile`; not modified, runs as a separate pcscd driver process |
| github.com/gorilla/websocket | v1.5.3 | BSD-2-Clause | allow | relay and helper WSS |
| gopkg.in/yaml.v3 | v3.0.1 | MIT AND Apache-2.0 | allow | allowlist parsing |

The Go versions are overrides in `components.yaml`; `scripts/license_register.py check` enforces them. The `smartcard` module itself is first-party.

## Evidence

- Code: `smartcard/`, `backend/app/routers/smartcard.py`, `backend/app/services/smartcard_tokens.py`, `backend/app/services/route_writer.py`.
- Tests: `smartcard/*/*_test.go`, `backend/tests/test_smartcard_tokens.py`, `frontend/src/components/launch/__tests__/smartcard-connect.test.tsx`.
- Runbooks: [smartcard-helper.md](../runbooks/smartcard-helper.md), [smartcard-helper-signing.md](../runbooks/smartcard-helper-signing.md).
