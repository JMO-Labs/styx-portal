# Smart-card helper: license check and owner actions

Decision: [ADR-0041](adr/0041-smart-card-passthrough-via-own-open-source-helper.md).

## License check against `license-policy.yaml`

Policy file: `docs/enterprise/license-policy.yaml` on the `enterprise` branch (allow / service_only / deny / proprietary lists; ADR-0041 is already an accepted exception ADR for signing costs). Result per component:

| Component | License (upstream) | Policy result | Notes |
|---|---|---|---|
| vsmartcard / virtualsmartcard (`vpcd`, `vicc`) | GPL-3.0 (verified from upstream `COPYING`) | Allowed (`GPL-3.0`) | Helper must be distributed under GPL-3.0-compatible terms with source offer; Styx's helper is open source by design (D41) |
| Windows virtual reader driver (BixVReader-derived) | LGPL-2.1 per upstream headers; **unverified, confirm from the tagged source** | Allowed (`LGPL-2.1`) if confirmed | Keep driver unmodified or publish changes |
| pcsc-lite in the desktop image | BSD-3-Clause | Allowed | Already in the image base |
| Windows WinSCard / macOS CryptoTokenKit | OS components | Not distributed | Not in register |
| Signing tools (signtool, notarytool, cosign) | Proprietary / Apache-2.0 | Build-only | signtool and notarytool are OS vendor tools, not redistributed; cost covered by ADR-0041 |

Policy gate: none are on `deny` or `proprietary`. GPL-3.0 means the gateway relay must not link vpcd code; it talks to it over the socket protocol only, keeping the relay licence-independent. Register entries (`components.yaml`, scope `enterprise`) are to be added with the implementation ticket, pinned to a tagged vsmartcard release; `scripts/license_register.py check` will then enforce it in CI.

## Owner actions

1. **Windows code-signing certificate:** buy an OV or EV Authenticode certificate (HSM or cloud signing service required for new certificates); store the key in the HSM, not in CI secrets. Recurring annual cost (ADR-0005).
2. **Apple Developer Program:** enrol the organization (annual fee, D-U-N-S number needed); create a Developer ID Application certificate and notarization credentials.
3. **MDM packaging:** confirm the MDM (Intune for Windows, Jamf or Intune for macOS); provide a signed MSI/MSIX and a signed, notarized pkg; define the deployment ring and the minimum-version policy.
4. **Driver signing:** decide how the Windows virtual reader driver gets a Microsoft-trusted signature (attestation signing via Hardware Dev Center needs an EV certificate).
5. **Security assessor:** schedule threat model review before Pilot 25.
6. **Confirm** the unverified BixVReader driver license from tagged source before adopting the fork.
