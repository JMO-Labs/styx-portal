# ADR-0062: Keycloak X.509 flow and HAProxy client-cert header format

- Status: Accepted
- Date: 2026-11-12
- Decision ID: D62
- Related controls: IA-2, IA-2(12), IA-5, IA-5(2), SC-23, AC-17
- Refines: ADR-0015, ADR-0016, ADR-0017, ADR-0050

## Context

Design section 7 left open how the DMZ HAProxy pair (ADR-0050) forwards the card certificate and how Keycloak maps it to an account. The HAProxy side already exists in `deploy/enterprise/dmz-haproxy` (issue #7). This ADR fixes the Keycloak side and records that the two agree.

## Decision

1. **Flow: browser-flow X.509 authenticator with the reverse-proxy cert lookup SPI.** Keycloak runs `--spi-x509cert-lookup--provider=haproxy` with `ssl-client-cert=Client-Cert`, `ssl-cert-chain=Client-Cert-Chain` and `certificate-chain-length=2`. The realm browser flow is "X509/Validate Username" with no password, OTP or WebAuthn alternative (D15). Break-glass admins (ADR-0025) use a separate flow bound only to the `master` realm admin client.
2. **Header format = existing template, no template change.** `Client-Cert` = `%[ssl_c_der,base64]` (leaf) and `Client-Cert-Chain` = `%[ssl_c_chain_der,base64]` (single value) match `haproxy.cfg.j2` rule 5 and Keycloak's documented `haproxy` provider. The deprecated `ssl-cert-chain-prefix` indexed headers are not used.
3. **PIV Authentication cert selection (D15).** HAProxy trusts only `dmz_piv_ca_file`. Keycloak then requires, on the leaf: key usage `digitalSignature`, and the PIV Authentication certificate policy OID (`2.16.840.1.101.3.2.1.3.13` for PIV Auth; `2.16.840.1.101.3.2.1.3.40` PIV-I Auth hardware; the DoD CAC equivalent for CAC) via the authenticator's certificate-policy check, and extended key usage `clientAuth`. Signing, encryption and Content-Signing certs fail these checks, so the browser's cert picker may offer them but login is refused.
4. **Identity extraction (D16).** The username/attribute mapper is a small Keycloak `UserIdentityExtractor` provider (one jar, built in CI, listed in the component register). It yields:
   - CAC: the 10-digit EDIPI, the trailing `.NNNNNNNNNN` of the subject CN;
   - PIV / PIV-I: the card UUID from the SAN URI `urn:uuid:<uuid>` (stock mappers cannot read SAN URIs).
   The extracted key is matched exactly against the hidden `edipi` / `piv_uuid` user attributes. No partial or name-only match logs in. An unbound key follows the D16 first-login binding path (admin review otherwise).
5. **Revocation (D17), fail closed.** The authenticator enables OCSP and CRL checking. OCSP responder per issuer: taken from each certificate's AIA, with `OCSP Fail-Open` off. CRL fallback reads a mirror by path (`crl-relative-path`, one file per issuer, refreshed by a CronJob) and aborts when the CRL is past `nextUpdate`. OCSP unreachable plus stale or missing CRL means login is refused with an alert. A CRL-age alert fires before `nextUpdate` (threshold set in the runbook). Break-glass is excepted (ADR-0025). Revocation stays out of HAProxy (no `crl-file`).
6. **Header spoofing control (IA-2, IA-5).** Three layers, all required:
   - HAProxy deletes client-supplied `Client-Cert`, `Client-Cert-Chain`, `X-Forwarded-*` and `Forwarded` on ingress, then sets the cert headers only on `login.<domain>` after a full, verified, non-resumed handshake.
   - Keycloak is reachable only from Traefik. A Cilium network policy admits Keycloak ingress from the Traefik pods alone; no other pod or node can reach it.
   - Traefik's dedicated entrypoint accepts connections only with the HAProxy client certificate (mTLS, ADR-0050), and a Traefik middleware strips `Client-Cert*` on every other router, including `provision`, `portal` and `banner`. Keycloak's `trusted-proxy`/proxy-headers settings list the Traefik entrypoint only.
   A request from any non-HAProxy source therefore either cannot reach Keycloak or has the headers removed.

## Alternatives considered

- **x509 direct grant (ROPC).** The client posts the cert to the token endpoint. It needs the cert terminated at the app, bypasses the browser flow and consent, and the direct-grant flow is deprecated in OAuth 2.1. Rejected.
- **Custom cert lookup SPI parsing a bespoke header.** More code to maintain for no gain over the stock `haproxy` provider. Rejected.
- **URL-encoded PEM header (nginx/apache providers).** Larger headers, extra escaping, and would need a template change. Rejected.
- **Revocation in HAProxy (`crl-file`).** HAProxy cannot do OCSP per issuer and needs reloads for CRL updates. Rejected (kept as in ADR-0017).

## Consequences

Positive:

- Zero HAProxy template change; header contract already documented and templated.
- Stock Keycloak flow plus one small extractor jar; fail-closed revocation matches D17.

Negative:

- The extractor jar is custom code to build, scan and pin on every Keycloak upgrade (D29).
- OCSP/AIA reachability from Keycloak to DoD and federal responders is a hard dependency; outages block login by design.
- Chain length is bounded at 2 intermediates beyond the leaf; deeper chains need `certificate-chain-length` raised.

Follow-up work:

- Build ticket: extractor jar and realm export (flow, policy OIDs, revocation settings, `trusted-proxy`).
- Cilium policy and Traefik strip middleware (#19 and its Traefik ticket) must implement layer 2 and 3 of the spoofing control; verify with a test that a forged `Client-Cert` sent directly to Traefik and to Keycloak is rejected.
- Verify policy OIDs and the AIA-per-issuer OCSP behaviour against the target Keycloak version in the build ticket.
