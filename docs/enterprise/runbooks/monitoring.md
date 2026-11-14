# Monitoring stack

Install and verify `kube-prometheus-stack` (release name `kube-prometheus-stack`,
namespace `monitoring`) and wire the Styx backend into it. Manifests live in
`deploy/monitoring/` (stack) and `deploy/k8s/` + `deploy/enterprise/` (styx
`ServiceMonitor`, `PrometheusRule`, SLO rules). The backend serves metrics on
port 9000, reachable only from the `monitoring` namespace
(`deploy/enterprise/networkpolicy.yaml`).

!!! warning "Compliance debt: resolve before deployment"
    R05 (SC-13 cryptographic protection, CM-6 configuration settings): no
    FIPS-validated crypto and no STIG baseline ([ADR-0011](../adr/0011-no-fips-or-stig-engineering-exceptions-recorded.md),
    still **Proposed**). The owner has waived R05 (Slack #wq-exec
    1794249302.942889) and states exceptions are obtained, but the ADR is not
    Accepted and the control-matrix rows are still `Planned`. Confirm the
    exceptions are recorded in eMASS and move ADR-0011 to Accepted before any
    deployment.

## 1. Install order

1. **CRDs first, applied server-side, as a separate step.** The CRDs are too
   large for client-side apply, and `deploy/monitoring/kustomization.yaml` sets
   `includeCRDs: false`. Major chart bumps must re-apply the CRDs the same way.

    ```bash
    helm show crds oci://ghcr.io/prometheus-community/charts/kube-prometheus-stack \
      --version 87.19.2 | kubectl apply --server-side --force-conflicts -f -
    ```

2. **The stack.** Renders the Helm chart through kustomize:

    ```bash
    kubectl kustomize --enable-helm deploy/monitoring | kubectl apply --server-side -f -
    ```

3. **Styx last.** Apply `deploy/enterprise` (or `deploy/k8s`) so the
   `ServiceMonitor` and `PrometheusRule` resources find their CRDs and the
   Prometheus that selects them.

## 2. Mirror and re-sign images into Harbor

Per [ADR-0029](../adr/0029-supply-chain-nightly-rebuild-scan-sign-sbom-harbor-kyverno-a.md),
Kyverno admits only signed images from Harbor, so upstream stack images must be
mirrored and re-signed before step 1.2.

1. List the images the chart renders (Prometheus, Alertmanager, Grafana,
   operator, config-reloader, node-exporter, kube-state-metrics, admission
   webhook patch).
2. Copy each into the Harbor proxy project (`skopeo copy --all`), scan with
   Trivy, and sign with the org cosign key.
3. Replace the placeholder `global.imageRegistry`
   (`harbor.example.invalid/proxy`) in `deploy/monitoring/values.yaml` with the
   real project, and make sure the `harbor-pull` secret exists in `monitoring`.
4. If pods sit in `ImagePullBackOff` or are rejected at admission, check the
   Kyverno policy report for the unsigned image.

## 3. RKE2 control-plane scrape targets

RKE2 binds etcd, kube-scheduler and kube-controller-manager metrics to
localhost, so the default targets show DOWN. Either expose them or disable the
targets.

**Expose** (in `/etc/rancher/rke2/config.yaml` on each server node, then
`systemctl restart rke2-server`):

```yaml
etcd-expose-metrics: true
kube-scheduler-arg:
  - bind-address=0.0.0.0
kube-controller-manager-arg:
  - bind-address=0.0.0.0
```

Then restrict the node firewall to the monitoring nodes, and point the chart at
RKE2 (`kubeEtcd.service.selector`, port 2381, plus the scheduler and
controller-manager endpoints) in `values.yaml`.

**Or disable** the targets in `values.yaml`:

```yaml
kubeEtcd: {enabled: false}
kubeScheduler: {enabled: false}
kubeControllerManager: {enabled: false}
```

`kubeProxy` is already disabled (Cilium kube-proxy replacement). Whichever you
choose, record it so the `KubeSchedulerDown`-style alerts are not left firing.

## 4. Storage class swap (after Rook-Ceph, #3)

`values.yaml` ships with `storageClassName: longhorn-styx` for Prometheus and
Alertmanager. Once Rook-Ceph is in place, change both
`volumeClaimTemplate`s to `rook-ceph-block`. A StatefulSet cannot change its
volume claim template in place: delete the StatefulSets with
`--cascade=orphan`, remove the old PVCs (history is lost unless you copy it),
and re-apply the stack so the operator recreates them. Do this in a
maintenance window.

## 5. Verify

```bash
kubectl -n monitoring get prometheus          # READY replicas match spec (2)
kubectl -n monitoring get pods                # all Running
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090
```

Open `http://localhost:9090/targets`: the `styx-backend` ServiceMonitor target
must be **UP** (scraping port 9000 through the NetworkPolicy). Open
`/rules` and confirm the styx and SLO rules are loaded. If the target is
missing, check the ServiceMonitor label `app: styx-backend` and that the
`metrics` port name exists on the Service; if it is DOWN, check the
NetworkPolicy allows the `monitoring` namespace.

## 6. Uninstall

Delete the stack, then the CRDs only if no other release uses them
(`kubectl delete crd` removes all `Prometheus` and `ServiceMonitor` objects).
