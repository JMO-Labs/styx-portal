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

Proxy namespace, name and port live only in `proxy-params.yaml`.

## Apply order

Allows first, default-deny last (the component lists them in this order):
`allow-dns`, `allow-apiserver`, `allow-webhooks`, then the remaining allows
(`allow-intra-ns-*`, `allow-prometheus`, `squid-proxy`, styx, traefik), and
`default-deny` last. `kubectl apply -k` is not ordered across kinds' names, so
for a first rollout apply everything except `default-deny`, verify, then apply
it alone:

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

Delete the deny; the allows are harmless alone:

```bash
kubectl delete ccnp default-deny
```

If a bad policy breaks workloads, `kubectl` still works (apiserver is
host-network); use the break-glass kubeconfig if the cluster API is unreachable
by other paths.

## Squid option B (off-cluster proxy)

If Squid runs off-cluster, replace the in-cluster `toEndpoints` proxy rule in
`patch-desktop-egress.yaml` with a /32 CIDR (not applied by default):

```yaml
# egress:
#   - toCIDR: ["203.0.113.10/32"]   # off-cluster Squid
#     toPorts:
#       - ports: [{port: "3128", protocol: TCP}]
```

## Manual connectivity matrix (kind + Cilium)

No offline policy evaluator exists, so this is manual or nightly: `cilium
install` 1.20.4 on kind, apply the overlay, run curl pods, and watch
`hubble observe --verdict DROPPED`.

| From | To | Expected |
|---|---|---|
| any pod | cluster DNS (53) | ok |
| non-desktop pod | kube-apiserver 6443 | ok |
| desktop (`styx-instances`) | Squid proxy 3128 | ok |
| desktop | world 443 direct | denied |
| desktop | world SSH 22 | denied |
| desktop | any UDP except DNS | denied |
