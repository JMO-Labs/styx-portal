# Runbook: node loss and desktop reattach

When a worker dies without draining, desktop pods stay `Terminating`/`Unknown` and their CephFS
(RWX) homes are not released. Kubernetes non-graceful node shutdown (ADR-0054) fixes this once
the node is tainted `node.kubernetes.io/out-of-service`. Tainting is a manual, human decision.

## Detection

- Alert `KubeNodeNotReady` / `KubeNodeUnreachable`, or `kubectl get nodes` shows `NotReady`.
- Desktop pods on the node stuck in `Terminating` or `Unknown`:
  `kubectl get pods -A -o wide --field-selector spec.nodeName=<node>`.
- Unrelated pods on other nodes are fine; only the dead node's pods are affected.

## When to taint

Taint only when **all** hold:

1. The node is `NotReady` and not coming back within minutes.
2. You have confirmed it is powered off, or fenced from the network and storage (IPMI/BMC
   power-off, switch port down). A node that is still running workloads and writing to Ceph
   risks two pods mounting the same home.
3. Waiting for the default eviction timeout (about 5 minutes) is not acceptable.

Do not taint a node that is merely draining or `Ready`; the script refuses a `Ready` node.

## Run the script

```bash
scripts/node-out-of-service.sh <node>          # prompts for confirmation
scripts/node-out-of-service.sh --yes <node>    # non-interactive
```

It checks the node is not `Ready`, asks for confirmation, and applies
`node.kubernetes.io/out-of-service=nodeshutdown:NoExecute`. Pods without a matching toleration
are force-deleted and their volumes detached.

## Verify reattach

```bash
kubectl get pods -A -o wide | grep -v <node>      # replacements Running on other nodes
kubectl get volumeattachments | grep <node>        # should drain to empty
```

- Each desktop Deployment shows a `Running` pod on a different node.
- Users reconnect and see their CephFS home intact.
- `ceph status` stays `HEALTH_OK`/`HEALTH_WARN` only for the lost OSDs (see [rook-ceph.md](rook-ceph.md)).

## Clear the taint after the node returns

Once the node is repaired and `Ready` again, remove the taint so it can schedule pods:

```bash
scripts/node-out-of-service.sh --clear <node>
kubectl get node <node> -o jsonpath='{.spec.taints}'   # no out-of-service entry
```

Clear it only after the node is back; clearing while it is still down is harmless, but leaving
it on a recovered node keeps pods from running there.

## CI

`scripts/kind/node-loss.sh` (the `kind-spike` check) stops a kind worker, runs the script, and
asserts the pod is rescheduled.
