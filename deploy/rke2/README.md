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
| CNI | `cilium` with kube-proxy replacement, encryption and Hubble (see [Cilium](#cilium)) |
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

## Cilium

RKE2 bundles the Cilium chart, so the chart version follows `rke2_version`:
`v1.36.6+rke2r1` ships `rke2-cilium` 1.20.400 (Cilium 1.20.4). **Upgrading Cilium
means bumping `rke2_version`**; then replace the vendored chart in `charts/` and
the version in `validate-cilium.sh` to match.

Our values live in `templates/rke2-cilium.yaml`, a `HelmChartConfig`
(`kube-system/rke2-cilium`). `masters.yml` lists it in `rke2_custom_manifests`,
so the role templates it into `/var/lib/rancher/rke2/server/manifests/` on every
server. The file deliberately has no `.j2` suffix: the role keeps the source file
name, and RKE2 only applies `.yaml`, `.yml` and `.json` files from that directory.
Its first line (`#jinja2: ...`) sets `lstrip_blocks` so Ansible renders it cleanly.

| Variable (`group_vars/all.yml`) | Default | Effect |
|---|---|---|
| `cilium_kube_proxy_replacement` | `true` | `kubeProxyReplacement: true`, API via `localhost:6443` (RKE2's local load balancer on every node, so the CNI does not depend on the keepalived VIP), `bpf.masquerade: true` |
| `disable_kube_proxy` | `"{{ cilium_kube_proxy_replacement }}"` | role writes `disable-kube-proxy: true`; tied to the line above so they cannot drift |
| `cilium_encryption_type` | `wireguard` | node-to-node encryption: `wireguard`, `ipsec` or `none`; any other value fails the chart schema and the tests |

Always on: Cilium agent metrics (`:9962`, metrics Service), operator metrics
(`:9963`), Hubble with relay and metrics (`:9965`, OpenMetrics) for `dns`, `drop`,
`flow` (namespace context only, to bound cardinality), `tcp`, `icmp` and
`port-distribution`. Hubble UI is off.

**ServiceMonitors are off on purpose.** Their CRDs do not exist when the CNI
installs on a new cluster, so enabling them would fail the chart and the cluster
would never get a network. The three ServiceMonitors (agent 9962, operator 9963,
Hubble 9965) belong to the monitoring overlay (#8), and the default-deny policy
(#19) must allow scraping those ports.

Prerequisites: kernel 5.8 or newer for kube-proxy replacement (Ubuntu 24.04 ships
6.8, with WireGuard built in).

### Switching encryption

- `wireguard` (default): Cilium creates and rotates the keys. **Not FIPS-validatable**
  (ChaCha20/Curve25519), recorded as SC-13 debt; IPsec is the exit if SC-13 must close.
- `ipsec`: create the Secret `kube-system/cilium-ipsec-keys` **out of band, before
  the first install** (Vault or env, then `kubectl create secret generic`; see the
  [Cilium IPsec guide](https://docs.cilium.io/en/stable/security/network/encryption-ipsec/)).
  Never ship it through `rke2_custom_manifests`: the role writes those files with
  mode 0644. Key rotation is manual. The tests fail on key material in this tree.
- `none`: no node-to-node encryption, which leaves an SC-8 gap.

Changing the type on a running cluster restarts the Cilium agents and briefly
interrupts pod traffic.

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
./validate-cilium.sh    # needs helm 3.22.1 and kubeconform 0.8.0 (CI pins and checks both)
```

`validate-cilium.sh` renders the HelmChartConfig with Ansible for each encryption
type, runs `helm template` on the vendored chart
`charts/rke2-cilium-1.20.400.tgz` with that `valuesContent`, and runs
`kubeconform -strict -kubernetes-version 1.36.6 -ignore-missing-schemas` on the
chart output and the HelmChartConfig. The chart is vendored (sha256
`5cf70c5a6f7cc21bfe8b38d7baca1a1171e1ab7130d92ad8a017bd7babc1a46e`, matching the `rke2-charts` index) because
`rke2-charts.rancher.io` was not reachable from the build environment; per D48,
mirror it in federal GitLab too. The chart's schema rejects a non-boolean
`encryption.enabled`, but it types `kubeProxyReplacement` as a string, so only
the pytest checks catch a bad value there.

## Known issues

- The worker label is `node.kubernetes.io/worker=true` instead of the
  `node-role.kubernetes.io/worker=true` the ticket first asked for (see the
  table above). `kubectl get nodes` therefore shows `<none>` in `ROLES` for
  agents. If that column matters, label the nodes after they join, from a
  server with the admin kubeconfig. No playbook task does this yet.
- The `site.yml` default-token check hashes the raw value, so a token padded
  with whitespace around the role's default token (a leading space, say) gets past
  it. Empty, whitespace-only and exact-default tokens are refused. Never derive
  the token from the role default; generate it with `openssl rand -hex 32`.
- The secret scan in `test_rke2_iac.py` accepts any `{{ ... }}` value, so a
  Jinja literal such as `token: "{{ 'abc' }}"` would not be flagged. Review
  token-like keys by hand.
- Nothing here has been applied to a real node. The CI job only lints and
  syntax-checks; Molecule against real RKE2 is out of scope.

## Open placeholders (TODO)

- Air-gap: Cilium images come from the RKE2 image tarball or Harbor (with the item below).

- Air-gap mode (`rke2_airgap_mode: false` for now) and pulling images through Harbor.
- The real VIP address and API DNS name (placeholders use RFC 5737 / `example.internal`).
- Node OS: Ubuntu 24.04 assumed.
