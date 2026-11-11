# Vendored Cilium CRD schemas (kubeconform)

Cilium **1.20.4** `CiliumNetworkPolicy` and `CiliumClusterwideNetworkPolicy` (`v2`) JSON schemas, vendored so kubeconform validates offline.

Generated from `https://github.com/cilium/cilium/tree/1.20.4/pkg/k8s/apis/cilium.io/client/crds/v2/` (`ciliumnetworkpolicies.yaml`, `ciliumclusterwidenetworkpolicies.yaml`) with kubeconform's `openapi2jsonschema.py` (yannh/kubeconform master; ported 1:1 to node/js-yaml because PyYAML was unavailable). Not the datree CRDs-catalog: it tracks latest Cilium.

Files are generated (~5.7k lines each) and exempt from the 500-line limit.

```bash
kubeconform -strict -summary -schema-location default \
  -schema-location 'deploy/k8s/components/cilium-baseline/schemas/{{.ResourceKind}}_{{.ResourceAPIVersion}}.json' -
```

## Local patch

In the `CIDRRule` `oneOf` (`toCIDRSet`/`fromCIDRSet`/`egressDeny`/`ingressDeny` etc.), the `cidr` branch forbids `except` via `additionalProperties: false`. The apiserver ignores this inside `oneOf`, so real clusters accept `cidr` + `except`; kubeconform does not. We add `"except": {}` to those branches (8 per file). Re-apply after regenerating.
