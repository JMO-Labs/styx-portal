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


# --- desktop egress patch + Squid proxy CCNP (#58) ---------------------------
FORBIDDEN_EGRESS = {"toCIDR", "toCIDRSet", "toFQDNs", "toEntities"}
SQUID = {"k8s:io.kubernetes.pod.namespace": "egress-proxy",
         "app.kubernetes.io/name": "squid"}


def _instances_cnp(docs):
    return next(d for d in docs if d["kind"] == "CiliumNetworkPolicy"
                and d["metadata"]["name"] == "instances")


def test_desktop_egress_only_dns_and_proxy():
    cnp = _instances_cnp(_render(OVERLAY))
    base = _instances_cnp(_render(K8S))
    dns, proxy = cnp["spec"]["egress"]
    assert len(cnp["spec"]["egress"]) == 2
    assert not any(FORBIDDEN_EGRESS & r.keys() for r in cnp["spec"]["egress"])
    assert dns["toEndpoints"] == base["spec"]["egress"][0]["toEndpoints"]
    assert dns["toPorts"][0]["rules"]["dns"] == [{"matchPattern": "*.cluster.local"}]
    assert dns["toPorts"][0]["ports"] == [{"port": "53", "protocol": "ANY"}]
    assert proxy["toEndpoints"] == [{"matchLabels": SQUID}]
    assert proxy["toPorts"] == [{"ports": [{"port": "3128", "protocol": "TCP"}]}]
    assert cnp["spec"]["egressDeny"] == base["spec"]["egressDeny"]
    assert cnp["spec"]["ingress"] == base["spec"]["ingress"]


def test_no_world_egress_for_desktops():
    for d in _render(OVERLAY):
        if d["kind"] not in {"CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy"}:
            continue
        sel = d["spec"].get("endpointSelector", {})
        if d["metadata"].get("namespace") not in (None, "styx-instances"):
            continue
        if sel.get("matchLabels") and d["kind"] == "CiliumClusterwideNetworkPolicy":
            continue  # selects specific pods (e.g. squid), not desktops
        if d["metadata"]["name"] in {"allow-apiserver", "allow-prometheus"}:
            continue
        for r in d["spec"].get("egress", []):
            assert not FORBIDDEN_EGRESS & r.keys(), d["metadata"]["name"]
            for p in r.get("toPorts", []):
                for port in p.get("ports", []):
                    assert port["port"] != "22"
                    if port["protocol"] == "UDP":
                        pytest.fail("UDP egress")


def test_proxy_params_single_source():
    files = [p for p in COMPONENT.iterdir()
             if p.is_file() and p.suffix in {".yaml", ".yml", ".json"}]
    for needle in ("egress-proxy", "3128"):
        hits = [p.name for p in files if needle in p.read_text()]
        assert len(hits) == 1, (needle, hits)
    assert (COMPONENT / "proxy-params.yaml").exists()


def test_squid_proxy_policy():
    docs = _render(OVERLAY)
    (c,) = [d for d in docs if d["kind"] == "CiliumClusterwideNetworkPolicy"
            and d["metadata"]["name"] == "squid-proxy"]
    assert c["spec"]["endpointSelector"]["matchLabels"] == SQUID
    (ing,) = c["spec"]["ingress"]
    assert ing["fromEndpoints"] == [{"matchLabels": {
        "k8s:io.kubernetes.pod.namespace": "styx-instances"}}]
    assert ing["toPorts"] == [{"ports": [{"port": "3128", "protocol": "TCP"}]}]
    egress = c["spec"]["egress"]
    assert {"toEntities": ["world"], "toPorts": [{"ports": [
        {"port": "80", "protocol": "TCP"}, {"port": "443", "protocol": "TCP"}]}]} in egress
    assert any("toEndpoints" in r and r["toPorts"][0]["ports"][0]["port"] == "53"
               for r in egress)
    # local-config params must not leak into the rendered output
    assert not any(d["kind"] == "ConfigMap" and d["metadata"]["name"] == "proxy-params"
                   for d in docs)
