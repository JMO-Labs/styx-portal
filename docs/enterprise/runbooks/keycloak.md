# Keycloak runbook

Deploy and operate Keycloak for CAC/PIV/PIV-I login from `deploy/enterprise/keycloak/` and
`deploy/enterprise/banner/` (issues #128-#133; ADR-0014, 0015, 0017, 0025, 0027, 0065, 0067).

## Deploy order

Each step needs the previous one. Commands assume the repository root.

1. **Prerequisites.** OpenBao and External Secrets are running ([openbao.md](openbao.md)); the
   DMZ HAProxy pair is deployed ([dmz-haproxy.md](dmz-haproxy.md)) with `dmz_piv_ca_file` set.
2. **Secrets in OpenBao.** Populate `kv/keycloak/breakglass-1` and `breakglass-2` (`username`,
   `password`) plus the bootstrap admin and DB secrets read by
   `deploy/enterprise/keycloak/external-secrets.yaml`. Never put them in the repository.
3. **Replace placeholders.** Search `deploy/enterprise/keycloak` and `deploy/enterprise/banner`
   for `PLACEHOLDER`: `KC_HOSTNAME`, the Harbor image digests, the `cephfs` storage class, the
   real issuer CRL URLs (`CRL_URLS`) and the banner `/start` redirect target.
4. **Apply.** `kubectl apply -k deploy/enterprise/keycloak` (namespace, ExternalSecrets,
   CNPG database, Keycloak, Cilium policy, PDB, CRL mirror, alerts), then
   `kubectl apply -k deploy/enterprise/banner`. Wait for `keycloak-db` to be healthy before
   Keycloak starts.
5. **Truststore.** Load the DoD and Federal PKI roots **and intermediates** into the Keycloak
   truststore (ADR-0065 item 2). Keycloak builds the chain itself.
6. **CRL mirror.** Run the first mirror by hand (below) so CRLs exist before the first login.
7. **Break-glass.** Run the bootstrap script (below) once.
8. **Verify.** Log in with a test card through the DMZ; confirm a login without a card is
   refused and that the `KeycloakCRLStale` and `KeycloakBreakGlassLogin` rules are loaded.

## Realm import

The `styx` realm (`realm/styx-realm.json`) is shipped as the `keycloak-realm` ConfigMap and
imported at start (`start --import-realm`, mounted at `/opt/keycloak/data/import`).

- Import only creates the realm when it does not exist. Editing the JSON does **not** change a
  running realm. Make later changes in the admin console or the admin API, then mirror them
  back into the JSON in the same PR so a rebuild matches.
- The browser flow is `x509-browser`: card only, no password, OTP or WebAuthn. Registration,
  direct grant and reset-credentials flows are denied.
- To rebuild: scale Keycloak to 0, drop the realm (or the database) deliberately, scale up.
  This logs everyone out and is a change-controlled action.

## CRL mirror operations

The `keycloak-crl-mirror` CronJob runs every 6 hours, fetches each issuer CRL from `CRL_URLS`,
writes it atomically to the `keycloak-crl` PVC (read-only in Keycloak) and pushes
`crl_next_update_timestamp_seconds` and `crl_mirror_last_success_timestamp_seconds` to the
Pushgateway (ADR-0017, ADR-0065 item 5).

- Run now: `kubectl -n keycloak create job --from=cronjob/keycloak-crl-mirror crl-manual-$(date +%s)`.
- Logs: `kubectl -n keycloak logs job/<job>`.
- Add an issuer: add `{"name": "url"}` to `CRL_URLS` in the `keycloak-crl-mirror` ConfigMap,
  add the matching `crl-relative-path` for that issuer in the realm, run the job.
- A CRL that is missing or past `nextUpdate` makes login fail closed even when OCSP works.

### CRL-age alert response

| Alert | Meaning | Response |
|---|---|---|
| `KeycloakCRLMirrorNotSucceeding` | No successful mirror for 12 h (2 schedule periods) or no metric | Check the last Job logs and the issuer distribution point. Fix egress (Squid allowlist, [squid-egress.md](squid-egress.md)) or the URL, then run the job by hand. This is a warning that precedes the next one. |
| `KeycloakCRLStale` (critical) | A CRL is past `nextUpdate`, for 5 min | Users of that issuer cannot log in if OCSP is also down. Run the job by hand. If the issuer publishes no newer CRL, escalate to the issuer and the security officer. Do **not** enable OCSP fail-open or delete the CRL check (ADR-0065). |

If cards from one issuer are blocked for longer than the business-hours target (ADR-0008),
break-glass is the only way in for administrators. Record it as below.

## Break-glass

Two local admins (password plus TOTP) exist in the `master` realm only (ADR-0025). The X.509
flow is not bound to `master`. The alert for any `master` login is `KeycloakBreakGlassLogin`
(see also [keycloak-breakglass.md](keycloak-breakglass.md)).

**Bootstrap (once, idempotent).** Port-forward `svc/keycloak`, export `KC_URL`, `KC_ADMIN_USER`,
`KC_ADMIN_PASSWORD` and the `BREAKGLASS_{1,2}_*` values from the `keycloak-breakglass` Secret,
then `python3 deploy/enterprise/keycloak/breakglass/breakglass_bootstrap.py --dry-run`, review,
and run it without `--dry-run`. Each admin enrols TOTP at first login (required action
`CONFIGURE_TOTP`). The script never prints passwords.

**Use.** Two key holders agree and record the reason before use. Fetch the credential from
OpenBao (`kv/keycloak/breakglass-N`), log in at the Keycloak admin URL, fix the problem, log out.

**Post-use review (security officer, within 2 business days).**

1. Match every `master` login event (Elastic and the alert) to a recorded reason and key holder.
   An event with no matching record is a security incident (IR-4).
2. Review the admin events from that session for changes beyond the stated purpose.
3. Rotate the used credential in OpenBao, let the ExternalSecret sync (up to 1 h) and re-run the
   bootstrap script so the account password and TOTP match; re-escrow the offline copy.
4. File the review result against the originating ticket.

## Banner host

The USG notice (ADR-0027) is served by the `banner` namespace (`deploy/enterprise/banner`) on a
host that does **not** request a client certificate, so users see it before the card prompt.
Its `/start` location redirects to the Styx start URL for the Keycloak provider
(`/api/auth/oauth/keycloak/start`), where the CAC mTLS happens on `login.<domain>`.

- Change the wording or redirect target in the `banner-site` ConfigMap, then
  `kubectl -n banner rollout restart deploy/banner`.
- The Styx login page redirects to the banner URL when one is configured (loop guard in place);
  if users loop, check that the banner host is not behind the client-cert listener.
- The IdP groups claim is mirrored into IdP-managed Styx groups at login (#133); roles come
  from the configured admin/user groups, never from open signup (ADR-0067).
