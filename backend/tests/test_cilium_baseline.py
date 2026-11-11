import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

K8S = Path(__file__).resolve().parents[2] / "deploy" / "k8s"
COMPONENT = K8S / "components" / "cilium-baseline"
OVERLAY = K8S.parent / "k8s-enterprise-netpol"
PEER_KEYS = {"fromEndpoints", "toEndpoints", "fromEntities", "toEntities",
             "fromCIDR", "fromCIDRSet", "toCIDR", "toCIDRSet"}


def _render(path):
    if shutil.which("kustomize"):
        cmd = ["kustomize", "build", str(path)]
    elif shutil.which("kubectl"):
        cmd = ["kubectl", "kustomize", str(path)]
    elif os.environ.get("REQUIRE_KUSTOMIZE") == "1":
        pytest.fail("kustomize/kubectl missing")
    else:
        pytest.skip("kustomize not installed")
    out = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return [d for d in yaml.safe_load_all(out) if d]


def _load(path):
    return yaml.safe_load(path.read_text())


def _ccnps():
    return [d for d in yaml.safe_load_all((COMPONENT / "ccnp-default-deny.yaml").read_text())
            if d]


def test_component_is_kustomize_component():
    k = _load(COMPONENT / "kustomization.yaml")
    assert k["apiVersion"] == "kustomize.config.k8s.io/v1alpha1"
    assert k["kind"] == "Component"
    assert "ccnp-default-deny.yaml" in k["resources"]


def test_overlay_uses_base_and_component():
    k = _load(OVERLAY / "kustomization.yaml")
    assert k["resources"] == ["../k8s"]
    assert k["components"] == ["../k8s/components/cilium-baseline"]
    kinds = {d["kind"] for d in _render(OVERLAY)}
    assert "CiliumClusterwideNetworkPolicy" in kinds


def test_base_build_has_no_ccnp():
    docs = _render(K8S)
    assert "CiliumClusterwideNetworkPolicy" not in {d["kind"] for d in docs}
    cnp = next(d for d in docs if d["kind"] == "CiliumNetworkPolicy"
               and d["metadata"]["name"] == "instances")
    assert any("toCIDRSet" in r for r in cnp["spec"]["egress"])


def test_default_deny_selects_all_but_kube_system():
    (d,) = [c for c in _ccnps() if c["metadata"]["name"] == "default-deny"]
    assert d["kind"] == "CiliumClusterwideNetworkPolicy"
    expr = d["spec"]["endpointSelector"]["matchExpressions"]
    assert expr == [{"key": "k8s:io.kubernetes.pod.namespace", "operator": "NotIn",
                     "values": ["kube-system"]}]
    assert d["spec"]["ingress"] == [{}]
    assert d["spec"]["egress"] == [{}]
    assert all(not PEER_KEYS & r.keys() for r in d["spec"]["ingress"] + d["spec"]["egress"])


def test_no_kube_system_in_any_allow_selector_changes():
    ccnps = [d for d in _render(OVERLAY) if d["kind"] == "CiliumClusterwideNetworkPolicy"]
    assert ccnps
    for c in ccnps:
        sel = c["spec"].get("endpointSelector", {})
        assert "kube-system" not in sel.get("matchLabels", {}).values()
        assert {"key": "k8s:io.kubernetes.pod.namespace", "operator": "NotIn",
                "values": ["kube-system"]} in sel.get("matchExpressions", [])


KS_NOT_IN = {"key": "k8s:io.kubernetes.pod.namespace", "operator": "NotIn",
             "values": ["kube-system"]}


def _allow(name):
    doc = _load(COMPONENT / f"ccnp-allow-{name}.yaml")
    assert doc["kind"] == "CiliumClusterwideNetworkPolicy"
    assert doc["metadata"]["name"] == f"allow-{name}"
    assert KS_NOT_IN in doc["spec"]["endpointSelector"]["matchExpressions"]
    return doc["spec"]


def _excluded_namespaces(spec):
    return {v for e in spec["endpointSelector"]["matchExpressions"]
            if e["key"] == "k8s:io.kubernetes.pod.namespace" and e["operator"] == "NotIn"
            for v in e["values"]}


def test_dns_allowed():
    rule = _allow("dns")["egress"][0]
    assert rule["toEndpoints"][0]["matchLabels"] == {
        "k8s:io.kubernetes.pod.namespace": "kube-system", "k8s-app": "kube-dns"}
    ports = rule["toPorts"][0]
    assert {(p["port"], p["protocol"]) for p in ports["ports"]} == {("53", "UDP"), ("53", "TCP")}
    assert ports["rules"]["dns"] == [{"matchPattern": "*"}]


def test_apiserver_allowed_on_6443():
    spec = _allow("apiserver")
    rule = spec["egress"][0]
    assert rule["toEntities"] == ["kube-apiserver"]
    assert [(p["port"], p["protocol"]) for p in rule["toPorts"][0]["ports"]] == [("6443", "TCP")]
    excluded = _excluded_namespaces(spec)
    assert {"styx-instances", "styx-egress-proxy"} <= excluded
    assert "traefik" not in excluded  # ingress providers watch the apiserver


def test_webhooks_ingress_from_apiserver():
    assert _allow("webhooks")["ingress"][0]["fromEntities"] == ["kube-apiserver"]


def test_component_lists_allow_policies():
    res = _load(COMPONENT / "kustomization.yaml")["resources"]
    assert res == ["ccnp-allow-dns.yaml", "ccnp-allow-apiserver.yaml",
                   "ccnp-allow-webhooks.yaml", "ccnp-default-deny.yaml"]
