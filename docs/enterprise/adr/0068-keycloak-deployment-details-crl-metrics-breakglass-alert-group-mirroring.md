# ADR-0068: Keycloak deployment details: CRL metrics, break-glass alert, group mirroring

- Status: Proposed
- Date: 2026-11-12
- Decision ID: D67
- Related controls: IA-2, IA-5(2), AC-2, AC-6, AC-8, AU-6
- Refines: ADR-0017, ADR-0025, ADR-0027, ADR-0065

## Context

Issues #128-#133 implemented the Keycloak deployment and left a few choices that no earlier ADR fixes. This records them for owner acceptance.

## Decision

1. **CRL metrics via Pushgateway.** The mirror CronJob is short-lived, so it POSTs `crl_next_update_timestamp_seconds{crl}` and `crl_mirror_last_success_timestamp_seconds` to the Pushgateway. `KeycloakCRLStale` fires 5 minutes after `nextUpdate` (critical). `KeycloakCRLMirrorNotSucceeding` fires after 12 hours (2 x the 6-hour schedule) without success or when the metric is absent. These are the ADR-0017 thresholds.
2. **Break-glass detection by user-event metrics.** Keycloak runs with `user-event-metrics` and counts `login` events. Any `master` realm login, successful or failed, raises `KeycloakBreakGlassLogin` to ops and the security officer. The post-use review is due within 2 business days, matching the account review rule (R04).
3. **Break-glass bootstrap is a script.** `breakglass_bootstrap.py` creates exactly two `master` admins with required TOTP and binds a password-plus-OTP flow in `master` only. Credentials come from OpenBao through External Secrets, never the repository.
4. **Realm as code, imported once.** The realm JSON is imported at start; later changes are made live and mirrored back to the JSON.
5. **Banner on its own host, groups mirrored.** The banner host requests no client certificate and redirects to the Styx start URL (ADR-0027). The IdP groups claim is mirrored into IdP-managed Styx groups; a user group is required for signup, so an empty configuration refuses signup rather than opening it (AC-6).

## Alternatives considered

- Scrape the CronJob pod: it does not live long enough to be scraped.
- Alert on Keycloak logs instead of metrics: slower to build, harder to test.

## Consequences

Positive:

- Every control named above has a deployed alert or script and a test.

Negative:

- The Pushgateway becomes a dependency of the CRL alerts.
- Live realm edits can drift from the JSON unless mirrored back.
