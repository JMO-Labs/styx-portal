# RKE2 node IaC (Ansible)

Installs a CIS-hardened RKE2 cluster: 3 HA control-plane (server) nodes in group
`masters` and 8 agents in group `workers`, using the community role
[`lablabs.rke2`](https://github.com/lablabs/ansible-role-rke2) pinned to `1.54.0`
(ADR-0006, ADR-0007).

> **Do not apply this to accredited environments.** The FIPS/STIG exception
> references (issuer, date, scope, eMASS artifact) cited by ADR-0011 are still
> missing, so SC-13 and CM-6 remain open compliance debt. Gate R05 was waived
> for writing this code only. Applying it to an accredited environment is
> forbidden until SC-13/CM-6 are closed.

## What it sets

| Setting | Value |
|---|---|
| RKE2 version | exact pin from the stable channel (`group_vars/all.yml`), no downgrades |
| Hardening | `rke2_cis_profile: cis`, apiserver `service-account-extend-token-expiration=false` |
| API HA | keepalived VIP (`rke2_api_ip`), VIP and DNS name in the TLS SANs; kube-vip off |
| CNI | `cilium` only; Cilium tuning and kube-proxy replacement are in #18 |
| Ingress | bundled ingress disabled |
| Servers | taint `CriticalAddonsOnly=true:NoExecute` |
| Agents | labels `node.kubernetes.io/worker=true`, `styx.io/gpu-ready=true` (not `node-role.kubernetes.io/*`: kubelet and NodeRestriction refuse that prefix in `--node-labels`, so agents would not register) |

The role's CIS task already creates the `etcd` user and installs the CIS
sysctls, so this tree does not repeat those steps.

## Usage

```bash
cd deploy/rke2
ansible-galaxy install -r requirements.yml       # installs into ./roles (gitignored)
cp inventory/hosts.example.yml inventory/hosts.yml   # set real names and IPs (gitignored)
# also set rke2_api_ip and rke2_additional_sans in inventory/group_vars/all.yml
export RKE2_TOKEN="$(openssl rand -hex 32)"     # or a CI masked variable
ansible-playbook -i inventory/hosts.yml site.yml
```

The cluster token comes from the `RKE2_TOKEN` environment variable. To use
Ansible Vault instead, override `rke2_token` with a vaulted value in a
non-committed vars file (`ansible-vault encrypt_string`) and pass it with `-e @file`.
`site.yml` stops before touching any node when the token is empty. Never commit
a token; the tests in `backend/tests/test_rke2_iac.py` fail on literal secrets.

## Pod Security Admission impact

`profile: cis` enforces PSA `restricted` in every namespace except
`kube-system` and a few RKE2 system namespaces. Workloads that need more must be
exempted explicitly in the `pod-security-admission-config-file` (follow-up work):

- Rook-Ceph (ADR-0033)
- the desktop namespace (D57 PSA exception, recorded in CM-6/CM-7)
- CloudNativePG (CNPG)
- monitoring (node exporters and similar)

Cilium runs in `kube-system`, so it is not affected. RKE2's built-in CIS
NetworkPolicies coexist with the default-deny baseline in #19.

## Break-glass escrow (D25)

After the first server comes up, escrow the admin kubeconfig
(`/etc/rancher/rke2/rke2.yaml`) and the cluster token **offline** (sealed, in
the safe) as well as in OpenBao. OpenBao runs inside the cluster, so it can
never be the only copy.

## Role provenance (D48)

Federal GitLab is the source of truth. Mirror `lablabs.rke2` 1.54.0 into
federal GitLab and point `requirements.yml` at the mirror (same exact version)
before any enterprise build. Never pull `latest` from Galaxy.

## CI

Job `rke2-iac` runs from this directory:

```bash
ansible-galaxy install -r requirements.yml
yamllint .
ansible-lint            # production profile, our files only
ansible-playbook -i inventory/hosts.example.yml site.yml --syntax-check
```

## Open placeholders (TODO)

- Air-gap mode (`rke2_airgap_mode: false` for now) and pulling images through Harbor.
- The real VIP address and API DNS name (placeholders use RFC 5737 / `example.internal`).
- Node OS: Ubuntu 24.04 assumed.
