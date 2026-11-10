# DMZ HAProxy pair runbook

Install and operate the two DMZ reverse proxies from `deploy/enterprise/dmz-haproxy/` (issue #7,
ADR-0012, ADR-0050). The header contract and what Traefik, Keycloak and Cilium must do are in
the IaC README, `deploy/enterprise/dmz-haproxy/README.md`.

!!! warning "Compliance debt"
    ADR-0011 is still Proposed. The FIPS/STIG exception references (issuer, date, scope,
    eMASS ID) are not cited, so SC-13 and CM-6 stay open. The TLS cipher, curve and version
    variables are placeholders until they are. Do not deploy to an accredited environment
    until then.

## Install

1. Copy `ansible/inventory.example.yml` to `hosts.yml`. Set both hosts' `ansible_host` and `dmz_peer_addr` (the address the other node reaches for VRRP and peers). Set `dmz_vrrp_state` (`MASTER` on one node, `BACKUP` on the other) and `dmz_vrrp_priority` (higher on the master).
2. Edit `ansible/group_vars/dmz.yml`: `dmz_domain`, `dmz_vip`, `dmz_provision_allowed_cidrs` (GCC High egress ranges, D20) and `dmz_traefik_servers`.
3. Put the VRRP secret (at most 8 characters) in ansible-vault as `vault_dmz_vrrp_auth_pass`.
4. Prepare a controller directory, outside the repo and on encrypted media, with `public.pem`, `login.pem`, `provision.pem`, `piv-roots.pem`, `openbao-ca.pem`, `cluster-ca.pem` and `haproxy-client.pem`. Server PEMs hold the full chain plus key. `haproxy-client.pem` is issued by the CA that Traefik's DMZ entrypoint trusts.
5. DMZ firewall: allow 443/tcp from the internet to the VIP; VRRP (IP protocol 112) and `dmz_peers_port`/tcp between the two nodes; and the nodes to the Traefik DMZ entrypoint.
6. Make sure the hosts' apt source carries `haproxy` 3.4.7 and `keepalived` 2.2.8.
7. Run:

    ```bash
    cd deploy/enterprise/dmz-haproxy/ansible
    ansible-playbook -i hosts.yml site.yml -e dmz_pki_src_dir=/secure/dmz-pki --ask-vault-pass --check --diff
    ansible-playbook -i hosts.yml site.yml -e dmz_pki_src_dir=/secure/dmz-pki --ask-vault-pass
    ```

8. Check: `ip addr` shows the VIP on the master only, and `curl -fsS http://127.0.0.1:8404/healthz` succeeds on both nodes.

## Certificate rotation

1. Put the new PEMs in the controller directory under the same names.
2. Run the playbook again. The copy task changes only the files that differ, `haproxy -c` validates the config, and the handler reloads HAProxy without dropping connections.
3. Check the served cert: `openssl s_client -connect <VIP>:443 -servername login.<domain> </dev/null | openssl x509 -noout -subject -enddate`.
4. Rotating `haproxy-client.pem` or `cluster-ca.pem`: update Traefik's DMZ TLSOption CA first if the issuing CA changes, then run the playbook. Otherwise every request fails with 503.
5. Adding a PIV-I or DoD CA: append it to `piv-roots.pem` and add the same CA to Keycloak's truststore.

## Failover test

1. On the master, `systemctl stop haproxy`. Within about 4 s (`fall 2` × `interval 2`) the VIP moves to the backup (`ip addr` on both nodes, `journalctl -u keepalived`).
2. From outside, `curl -sv https://portal.<domain>/` still answers.
3. `systemctl start haproxy` on the old master. The VIP moves back (higher priority).
4. Record the date and the measured failover time.

## Header verification

Run these from a host in an allowed client network, against the VIP:

| Check | Command | Expected |
|---|---|---|
| No card on login | `curl -s -o /dev/null -w '%{http_code}' https://login.<domain>/` | `403` and the no-card page |
| Spoofed header dropped | `curl -s -H 'Client-Cert: AAAA' https://portal.<domain>/` while a debug echo route is attached in Traefik | No `Client-Cert` reaches the backend |
| Domain fronting | `curl -s -o /dev/null -w '%{http_code}' --cert card.pem --key card.key --resolve login.<domain>:443:<VIP> -H 'Host: portal.<domain>' https://login.<domain>/` | `421` |
| Trailing-dot Host | `curl -s -o /dev/null -w '%{http_code}' -H 'Host: provision.<domain>.' https://portal.<domain>/` | `421` |
| Unknown Host | `curl -s -o /dev/null -w '%{http_code}' -H 'Host: other.example' https://portal.<domain>/` | `421` |
| Provision outside the allowlist | `curl ... https://provision.<domain>/` from a non-GCC High source with a valid OpenBao cert | `403` |
| Valid card | Sign in with a CAC in a browser | Keycloak shows the x509 user; its log shows the `haproxy` lookup provider |

The CI job `dmz-haproxy-integration` runs the same checks against a real HAProxy on every pipeline.
