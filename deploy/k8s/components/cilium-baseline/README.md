# Cilium baseline (opt-in)

Cluster-wide default-deny plus explicit allows, and a desktop egress patch that
leaves desktops only DNS (`*.cluster.local`) and the Squid proxy. Status:
implemented in code, not deployed. The Squid and HAProxy parts themselves are
not done; this component only allows traffic to Squid.

`kube-system` is never selected. `kube-apiserver` is host-network, so `kubectl`
keeps working with a bad policy; keep the break-glass offline kubeconfig (D25).

## Opt-in

The base `deploy/k8s` build has no CCNPs. Enable the baseline with the overlay
(it uses `components: [../k8s/components/cilium-baseline]`):

```bash
kubectl kustomize deploy/k8s-enterprise-netpol   # review
kubectl apply -k deploy/k8s-enterprise-netpol    # see "Apply order" below
```

Proxy namespace, name and ports live only in `proxy-params.yaml`.

## Proxy ports and egress mode

Squid listens on two ports; Cilium routes each desktop to one by pod label
`styx.io/egress-mode` (set by Styx; values `category` / `allowlist`):

| Desktop label | Policy | Squid port |
|---|---|---|
| `styx.io/egress-mode: allowlist` | `desktop-proxy-allowlist` | `allowlistPort` (3129) |
| anything else (`category`, unlabeled) | `desktop-proxy-category` | `port` (3128) |

Cilium allows are a union, so the selectors are mutually exclusive: an
allowlist desktop never matches the 3128 rule and cannot bypass the allowlist by
switching ports. `squid-proxy` ingress allows both ports from `styx-instances`.

## Apply order

**First rollout: enable audit mode first** (see "Audit-mode rollout"). Every
allow policy already enables default-deny for the direction and endpoints it
selects (no CCNP here sets `enableDefaultDeny: false`; `allow-dns` egress and
`allow-webhooks` ingress select every namespace except kube-system). So
applying the allows without `default-deny` still enforces; it is not a "verify"
gate.

`kubectl apply -k` gives no ordering guarantee. Allows-first, deny-last is
ordering hygiene only (the manifests are not listed in that order in
`kustomization.yaml`), done with a split apply:

```bash
kubectl kustomize deploy/k8s-enterprise-netpol \
  | yq 'select(.metadata.name != "default-deny")' | kubectl apply -f -
kubectl apply -f deploy/k8s/components/cilium-baseline/ccnp-default-deny.yaml
```

## Audit-mode rollout

Observe before enforcing. Enable policy audit mode, then apply everything:

- Helm / RKE2: `policyAuditMode: true` in the Cilium HelmChartConfig (#18), or
- live: `cilium config set policy-audit-mode true`

```bash
hubble observe --verdict AUDIT --follow
```

Every AUDIT line is a flow that would be dropped. Add allows until only
expected flows remain, then set `policyAuditMode: false` (or
`cilium config set policy-audit-mode false`) and confirm with
`hubble observe --verdict DROPPED`.

## Rollback

`kubectl delete ccnp default-deny` is only a **partial** first step: the allow
policies still select endpoints and keep default-deny on (pods stay egress-denied
except DNS, ingress-denied except the apiserver). Full rollback removes all
baseline CCNPs and restores the un-patched `instances` policy. Do not use
`kubectl delete -k` on the overlay: it also contains the base workloads.

```bash
kubectl kustomize deploy/k8s-enterprise-netpol \
  | yq 'select(.kind == "CiliumClusterwideNetworkPolicy")' | kubectl delete -f -
# or by name: default-deny allow-dns allow-apiserver allow-webhooks squid-proxy
#   styx traefik allow-prometheus allow-prometheus-egress allow-intra-ns-<ns>...
kubectl -n styx-instances delete cnp desktop-proxy-category desktop-proxy-allowlist
kubectl apply -f deploy/k8s/instances.yaml   # un-patched instances CNP from base
```

Alternatively set `policyAuditMode: true` to stop enforcement without deleting.
If a bad policy breaks workloads, `kubectl` still works (apiserver is
host-network); use the break-glass kubeconfig if the cluster API is unreachable
by other paths.

## Squid option B (off-cluster proxy)

If Squid runs off-cluster, replace the in-cluster `toEndpoints` proxy rules in
`cnp-desktop-proxy.yaml` with a /32 CIDR (not applied by default):

```yaml
# egress:
#   - toCIDR: ["203.0.113.10/32"]   # off-cluster Squid
#     toPorts:
#       - ports: [{port: "3128", protocol: TCP}]
```

Also remove (or retarget) the `desktop-proxy-*`
replacement targets in `kustomization.yaml` (namespace and name, both under
`spec.egress.0.toEndpoints.0.matchLabels` of `desktop-proxy-*`); with `create: true` they would put
`toEndpoints` back into the CIDR rule. The port replacement still applies to
`spec.egress.0.toPorts`.

## Manual connectivity matrix (kind + Cilium)

No offline policy evaluator exists, so this is manual or nightly: `cilium
install` 1.20.4 on kind, apply the overlay, run curl pods, and watch
`hubble observe --verdict DROPPED`.

| From | To | Expected |
|---|---|---|
| any pod | cluster DNS (53) | ok |
| non-desktop pod | kube-apiserver 6443 | ok |
| desktop (`styx-instances`) | Squid proxy 3128 | ok |
| allowlist desktop | Squid proxy 3128 | denied |
| allowlist desktop | Squid proxy 3129 | ok |
| category desktop | Squid proxy 3129 | denied |
| desktop | world 443 direct | denied |
| desktop | world SSH 22 | denied |
| desktop | any UDP except DNS | denied |
