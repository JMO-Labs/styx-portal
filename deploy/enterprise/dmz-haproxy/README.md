# DMZ HAProxy pair (issue #7, ADR-0012, ADR-0050)

Ansible role and playbook for the two DMZ reverse proxies (D06). Nothing here has been applied to a host.

- HAProxy **3.4.7** (current LTS) and keepalived **2.2.8**, pinned in `roles/dmz_haproxy/defaults/main.yml` and held with `dpkg`. The hosts run Ubuntu 24.04. Their apt source, an org mirror of the HAProxy 3.4 LTS packages, must carry these exact versions.
- **Active/passive** with one floating VIP (`dmz_vip`). keepalived uses unicast VRRP (`unicast_peer`, because DMZ switches often drop multicast). The node holds the VIP only while its local `/healthz` frontend (`127.0.0.1:8404`) answers. The org firewall NATs public 443 to the VIP.
- The two nodes share rate-limit counters through the `peers` section on `dmz_peers_port`, so a failover keeps them.
- Runbook: [docs/enterprise/runbooks/dmz-haproxy.md](../../../docs/enterprise/runbooks/dmz-haproxy.md).

## Layout

| Path | What |
|---|---|
| `ansible/site.yml` | Applies the `dmz_haproxy` role to group `dmz` |
| `ansible/inventory.example.yml` | Two hosts with per-host `dmz_peer_addr`, `dmz_vrrp_state` and `dmz_vrrp_priority` |
| `ansible/group_vars/dmz.yml` | Site values: domain, VIP, provision CIDRs, Traefik servers, vaulted VRRP secret |
| `roles/dmz_haproxy/defaults/main.yml` | Versions, paths, TLS policy, ports, rate limits |
| `templates/haproxy.cfg.j2`, `crt-list.j2`, `keepalived.conf.j2` | Rendered configs. `haproxy.cfg` is validated with `haproxy -c -f`, and `keepalived.conf` with `keepalived -t -f` |
| `files/errors/no-card.html` | Styx-styled 403 page for `login.<domain>` without a verified card |

## Hosts and client certificates (D49)

| Host | Client cert | Trust | Forwarded to the cluster |
|---|---|---|---|
| `banner.<domain>`, `portal.<domain>` | not requested (`verify none`) | none | No cert headers |
| `login.<domain>` | requested (`verify optional`) | `dmz_piv_ca_file` (DoD / PIV-I roots and intermediates) | `Client-Cert` and `Client-Cert-Chain`, only after a verified handshake |
| `provision.<domain>` | required (`verify required`) | `dmz_openbao_ca_file` (OpenBao PKI) | No cert headers. The source must be in `dmz_provision_allowed_cidrs` (GCC High, D20) |

A failed verification aborts the handshake. No entry sets `ca-ignore-err` or `crt-ignore-err`, and no `crl-file` is used: revocation stays in Keycloak (ADR-0017). `verify optional` on login exists only so that a missing card gets the styled page instead of a bare TLS error.

## Header contract (what HAProxy guarantees to Traefik and Keycloak)

1. On every host, the first `http-request` rules delete any client-supplied `Client-Cert`, `Client-Cert-Chain`, `X-Forwarded-For`, `X-Forwarded-Proto`, `X-Forwarded-Host` and `Forwarded`.
2. On `login.<domain>` and `provision.<domain>`, the TLS SNI must equal the `Host` header (lowercased, port stripped). Otherwise the answer is **421** (domain fronting). A request with `Host: login.<domain>` on any other SNI also gets 421.
3. `provision.<domain>` from outside `dmz_provision_allowed_cidrs` gets **403**. Per-source-IP limits (`dmz_login_rate_limit`, `dmz_provision_rate_limit` per `dmz_ratelimit_period`) return **429**.
4. `login.<domain>` without a verified client cert gets the **403** `no-card.html` page, and nothing reaches the cluster.
5. Only on `login.<domain>`, and only when `ssl_c_used` and `ssl_c_verify 0`:
   - `Client-Cert` = `%[ssl_c_der,base64]`: base64 DER of the client leaf.
   - `Client-Cert-Chain` = `%[ssl_c_chain_der,base64]`: base64 DER of the certs the client sent after the leaf. It may be empty, because CAC/PIV middleware usually sends only the leaf.

   This is the format of Keycloak's `haproxy` x509cert-lookup provider.
6. HAProxy sets `X-Forwarded-Proto: https` and appends `X-Forwarded-For` with the client source address.
7. TLS resumption is off on every host. HAProxy documents that `ssl_c_chain_der` does not support resumed sessions, and a TLS 1.3 session from `provision.<domain>` could otherwise resume on `login.<domain>` and pass its OpenBao cert as a card. The bind sets `no-tls-tickets` (a bind-only keyword, so it cannot go in a crt-list line), and `tune.ssl.cachesize 0` disables the stateful cache (TLS 1.2 session IDs and TLS 1.3 PSK). As defence in depth, the cert headers are set only when `!{ ssl_fc_is_resumed }`, and a resumed login gets the no-card page. CI covers this with `test_resumed_session_never_half_set` (the card sends a chain) and `test_provision_session_resumed_on_login_never_sets_header`. Even so, Keycloak must not rely on `Client-Cert-Chain` (see below).

HAProxy re-encrypts to Traefik over mTLS: `ssl verify required ca-file {{ dmz_cluster_ca_file }} crt {{ dmz_haproxy_client_cert }}`, with SNI and `verifyhost` = `dmz_traefik_sni`. It never uses `verify none`.

## What the other tickets must do

**Keycloak (Phase 2 Keycloak ticket):**

```
--spi-x509cert-lookup--provider=haproxy
--spi-x509cert-lookup--haproxy--ssl-client-cert=Client-Cert
--spi-x509cert-lookup--haproxy--ssl-cert-chain=Client-Cert-Chain
--spi-x509cert-lookup--haproxy--certificate-chain-length=<var, default 3; longer for PIV-I via the Federal Bridge>
--proxy-headers=xforwarded
--proxy-trusted-addresses=<Traefik pod CIDR>
```

Keycloak revalidates the chain against its own truststore, so the DoD and PIV-I roots **and intermediates** must be in that truststore. Do not rely on `Client-Cert-Chain`. The x509 lookup SPI is server-wide, so keep the Keycloak admin endpoints off the public entrypoint.

**Traefik (Traefik ticket):**

- A dedicated DMZ entrypoint with a TLSOption that sets `clientAuth.clientAuthType: RequireAndVerifyClientCert` and `clientAuth.caFiles` = the CA that issues `dmz_haproxy_client_cert`. This makes "only the proxy may set the header" cryptographic.
- `forwardedHeaders.trustedIPs` on that entrypoint = the two DMZ node addresses only. The VIP is not the source address.
- Every other entrypoint (internal, admin) gets a `headers` middleware that sets `Client-Cert` and `Client-Cert-Chain` to empty, which removes them.

**Cilium (#19):** only Traefik pods may reach Keycloak on 8080/8443. `proxy-trusted-addresses` sees the Traefik pod IP, so the Cilium policy is the real control, and the Keycloak setting is defence in depth.

## Inputs

- `dmz_pki_src_dir` (required, `-e`): a controller directory with `public.pem`, `login.pem`, `provision.pem` (each cert chain + key), `piv-roots.pem`, `openbao-ca.pem`, `cluster-ca.pem` and `haproxy-client.pem` (cert + key). The issuer is the org's call (D12/D49), so nothing here generates certs. Never commit these files.
- `vault_dmz_vrrp_auth_pass`: up to 8 characters, in ansible-vault.
- `dmz_provision_allowed_cidrs`: the GCC High egress ranges for the provisioning webhook. The value committed here is a documentation placeholder.

## Compliance debt (R05)

Gate R05 was waived by the owner for code only (Slack #wq-exec 1794257851.219479). ADR-0011 stays Proposed. The FIPS/STIG exception references (issuer, date, scope, eMASS ID) are still open compliance debt (SC-13, CM-6). The TLS variables (`dmz_tls_ciphers`, `dmz_tls_ciphersuites`, `dmz_tls_min_ver`, `dmz_tls_curves`) are placeholders until that is resolved. **Do not deploy** before then.

## CI

- `dmz-haproxy-iac`: yamllint, ansible-lint, `ansible-playbook --syntax-check`, then renders the templates and runs `haproxy -c -f` (`-k config_check`).
- `dmz-haproxy-integration`: `backend/tests/integration/test_dmz_haproxy.py` with `HAPROXY_IT=1` against real HAProxy, a throwaway PKI and an mTLS echo backend standing in for Traefik.

Both jobs run in the official `haproxy:3.4.7` image pinned by digest. Static checks: `backend/tests/test_enterprise_dmz_haproxy.py`.
