# ADR-0041: Smart-card passthrough via own open-source helper (phase 4)

- Status: Proposed
- Date: 2026-10-28
- Decision ID: D41
- Related controls: IA-2(12), SA-8, SA-11, SC-12

## Context

Browsers cannot reach card readers; commercial options carry licenses.

Source: docs/enterprise/design.md section 5.

## Decision

Build an own open-source helper (vpcd/virtualsmartcard-based), signed (Windows code-signing certificate, Apple developer program) and MDM-pushed, Windows first then macOS. It relays PC/SC only to the user's own session, authenticates with its own CAC mTLS plus a per-session one-time token, enforces an APDU allowlist, allows signing only with user interaction, and has its own threat model. Delivered in phase 4 because pilots need the card inside the desktop.

## Architecture

- **Components:** `styx-card-helper` on the user's workstation (Windows first, macOS second) and a relay endpoint in the Styx gateway. The helper exposes the physical reader's PC/SC interface; inside the desktop container a `vpcd`/`vicc` virtual reader (virtualsmartcard) presents it to the session's PC/SC stack (pcscd).
- **Transport:** one outbound WebSocket over TLS 1.3 from helper to gateway (no inbound port on the workstation). The relay binds the helper connection to exactly one desktop session; it never routes across sessions or users.
- **Authentication:** (1) mutual TLS with the user's own CAC/PIV certificate, validated like a portal login (D15, D17 OCSP); (2) a per-session one-time token minted by Styx when the session starts, 128-bit random, single use, 60 s TTL, bound to session ID and EDIPI/UUID (D16). Both must match the logged-in session owner or the relay refuses.
- **APDU allowlist:** deny by default, enforced in the helper and again in the relay. Allowed: SELECT of the PIV/CAC applets, GET DATA for certificates, VERIFY (PIN is entered at the reader or in the desktop, never logged), GENERAL AUTHENTICATE for signature/auth. Denied: PUT DATA, CHANGE/RESET RETRY COUNTER, key generation/import, card management and vendor commands. The list is a versioned file shipped signed with the helper.
- **User interaction:** each signature operation requires a visible helper prompt (name of the requesting desktop session, operation count) confirmed by the user; no silent signing, rate-limited per session.
- **Update and signing path:** reproducible CI build, SBOM, Windows binary and driver Authenticode-signed (EV or OV certificate), macOS binary Developer-ID signed and notarized, releases signed also with cosign (D29). Distribution only via MDM (Intune/Jamf); the helper has no self-update channel and checks a minimum-version floor at connect, refusing to relay when outdated.
- **Logging:** metadata only (session, time, allowed/denied APDU class, counts) to the audit trail; never APDU payloads, PIN or certificate contents.

Threat model: [smart-card-helper-threat-model.md](../smart-card-helper-threat-model.md). License check and owner actions: [smart-card-helper-licenses-and-owner-actions.md](../smart-card-helper-licenses-and-owner-actions.md).

## Alternatives considered

Entries beyond those recorded in design.md are the obvious options, not documented discussion.

- Commercial passthrough - license fees.
- No passthrough - blocks in-desktop CAC use.

## Consequences

Positive:

- No license fees; control of implementation.

Negative:

- Custom security-critical code to maintain and assess.
- On the critical path for Pilot 25.
- Signing certificates are a recurring cost (ADR-0005).

Follow-up work:

- Threat model (written, see above) reviewed by the security assessor before Pilot 25.
- Owner actions (certificates, Apple program, MDM packaging) tracked in the linked document.
- Implementation tickets follow once this ADR is approved.
