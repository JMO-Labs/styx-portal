# Smart-card helper threat model (STRIDE)

Scope: `styx-card-helper` (workstation), gateway relay, virtual reader in the desktop session. Decision: [ADR-0041](adr/0041-smart-card-passthrough-via-own-open-source-helper.md). Status: Proposed.

## Assets

Card private keys (never leave the card), PIN, certificates, the signing capability, the session binding.

## Trust boundaries

1. Workstation (user-controlled, may be malware-infected) to gateway.
2. Gateway relay to desktop container.
3. Desktop session (runs user-chosen software) to virtual reader.

## STRIDE

| ID | Threat | Mitigation |
|---|---|---|
| S1 | Rogue client impersonates the helper | mTLS with the user's CAC/PIV cert, OCSP-checked (D17); one-time session token bound to session and cert identity |
| S2 | Attacker replays a captured token | Single use, 60 s TTL, bound to TLS channel and session ID; consumed on first accept |
| S3 | Fake gateway tricks helper into relaying | Helper pins the Styx gateway CA; refuses other servers |
| S4 | Another user's session receives the card | Relay maps one helper connection to one session owned by the same EDIPI/UUID; cross-user routing is a hard refusal, alerted |
| T1 | APDU tampering in transit | TLS 1.3 end to end; relay and helper both enforce the allowlist |
| T2 | Modified helper binary or allowlist | Signed binaries and signed allowlist; MDM-only distribution; integrity verified at start; version floor at connect |
| T3 | Malicious desktop software sends dangerous APDUs | Deny-by-default allowlist excludes PUT DATA, PIN change/reset, key generation, vendor commands |
| R1 | User denies a signing operation | Helper prompt confirmation recorded as audit metadata (session, time, count); gateway log is append-only (AU-9) |
| R2 | Admin disputes a denied APDU | Denied-class events are logged with the reason |
| I1 | PIN or certificate leaks through logs | Payloads, PINs and certificate contents never logged; PIN entry at reader or in-session only |
| I2 | Card reachable by other local processes via the virtual reader | Virtual reader lives only in the user's container PC/SC namespace; rootless container, no shared pcscd socket |
| I3 | Traffic metadata exposure | Only outbound TLS; no inbound listener; metadata limited to what the audit trail already holds |
| D1 | Relay flooded or card locked by PIN-retry attacks | Per-session rate limit; VERIFY attempt cap below card retry counter (stop at one remaining try, require user action); connection cap per user |
| D2 | Helper crash leaves session without card | Session shows a clear card-absent state; user reconnects. Accepted: availability of in-desktop CAC is best effort |
| E1 | Malware on the workstation uses the helper to sign silently | Every signature requires a visible user confirmation in the helper UI; rate limit; user-interaction prompt not scriptable from the desktop session |
| E2 | Helper update channel abused for code delivery | No self-update; MDM push of signed packages only |
| E3 | Driver (vpcd) vulnerability gives kernel-level escalation | Windows UMDF user-mode driver; track upstream CVEs through the component register; pinned, reviewed fork |

## Residual risks

- Compromised workstation with the user present can approve a prompt (social engineering). Accepted; same exposure as a locally attached reader.
- Upstream vsmartcard is a small-maintainer project: Styx must own a reviewed fork and its patches (see licenses document).
- Key operations are protected by the card, but relayed use of the key during an active session is real use; session timeouts (D41 phase 4 siblings) limit exposure.

## Review

Security assessor review before Pilot 25; re-review on any allowlist change.
