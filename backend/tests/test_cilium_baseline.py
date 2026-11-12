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
        ns = sel.get("matchLabels", {}).get("k8s:io.kubernetes.pod.namespace")
        if ns:  # pod-specific selector (e.g. squid) pinned to one namespace
            assert ns != "kube-system"
            continue
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


def _rendered(name):
    return next(d for d in _render(OVERLAY)
                if d["kind"] == "CiliumClusterwideNetworkPolicy"
                and d["metadata"]["name"] == name)["spec"]


def test_dns_excludes_desktops():
    # desktops get **.cluster.local-only DNS from the patched instances CNP;
    # a cluster-wide "*" pattern would widen it (Cilium allows are a union)
    assert "styx-instances" in _excluded_namespaces(_allow("dns"))


def test_apiserver_allowed_on_6443():
    spec = _allow("apiserver")
    rule = spec["egress"][0]
    assert rule["toEntities"] == ["kube-apiserver"]
    assert [(p["port"], p["protocol"]) for p in rule["toPorts"][0]["ports"]] == [("6443", "TCP")]
    proxy_ns = _load(COMPONENT / "proxy-params.yaml")["data"]["namespace"]
    excluded = _excluded_namespaces(_rendered("allow-apiserver"))
    assert {"styx-instances", proxy_ns} <= excluded
    assert "traefik" not in excluded  # ingress providers watch the apiserver


def test_webhooks_ingress_from_apiserver():
    assert _allow("webhooks")["ingress"][0]["fromEntities"] == ["kube-apiserver"]


def test_component_lists_allow_policies():
    res = _load(COMPONENT / "kustomization.yaml")["resources"]
    assert res[:4] == ["ccnp-allow-dns.yaml", "ccnp-allow-apiserver.yaml",
                       "ccnp-allow-webhooks.yaml", "ccnp-default-deny.yaml"]


# --- desktop egress patch + Squid proxy CCNP (#58) ---------------------------
FORBIDDEN_EGRESS = {"toCIDR", "toCIDRSet", "toFQDNs", "toEntities"}
SQUID = {"k8s:io.kubernetes.pod.namespace": "egress-proxy",
         "app.kubernetes.io/name": "squid"}


def _instances_cnp(docs):
    return next(d for d in docs if d["kind"] == "CiliumNetworkPolicy"
                and d["metadata"]["name"] == "instances")


def _cnp(docs, name):
    return next(d for d in docs if d["kind"] == "CiliumNetworkPolicy"
                and d["metadata"]["name"] == name)


def test_desktop_egress_only_dns():
    cnp = _instances_cnp(_render(OVERLAY))
    base = _instances_cnp(_render(K8S))
    (dns,) = cnp["spec"]["egress"]
    assert not FORBIDDEN_EGRESS & dns.keys()
    assert dns["toEndpoints"] == base["spec"]["egress"][0]["toEndpoints"]
    assert dns["toPorts"][0]["rules"]["dns"] == [{"matchPattern": "**.cluster.local"}]
    assert dns["toPorts"][0]["ports"] == [{"port": "53", "protocol": "ANY"}]
    assert cnp["spec"]["egressDeny"] == base["spec"]["egressDeny"]
    assert cnp["spec"]["ingress"] == base["spec"]["ingress"]


def test_proxy_port_by_egress_mode():
    docs = _render(OVERLAY)
    cat = _cnp(docs, "desktop-proxy-category")
    allow = _cnp(docs, "desktop-proxy-allowlist")
    for c, port in ((cat, "3128"), (allow, "3129")):
        assert c["metadata"]["namespace"] == "styx-instances"
        (rule,) = c["spec"]["egress"]
        assert rule["toEndpoints"] == [{"matchLabels": SQUID}]
        assert rule["toPorts"] == [{"ports": [{"port": port, "protocol": "TCP"}]}]
        assert not FORBIDDEN_EGRESS & rule.keys()
    # selectors are mutually exclusive (allows are a union)
    assert allow["spec"]["endpointSelector"] == {
        "matchLabels": {"styx.io/egress-mode": "allowlist"}}
    assert cat["spec"]["endpointSelector"] == {"matchExpressions": [
        {"key": "styx.io/egress-mode", "operator": "NotIn", "values": ["allowlist"]}]}


def test_allowlist_port_param():
    assert _load(COMPONENT / "proxy-params.yaml")["data"]["allowlistPort"] == "3129"


NS_KEY = "k8s:io.kubernetes.pod.namespace"
INFRA_ALLOWS = {"allow-apiserver", "allow-prometheus"}


def _can_select_desktops(sel):
    """False only if the selector provably cannot match styx-instances pods."""
    ns = sel.get("matchLabels", {}).get(NS_KEY)
    if ns is not None and ns != "styx-instances":
        return False
    for e in sel.get("matchExpressions", []):
        if e["key"] == NS_KEY:
            if e["operator"] == "NotIn" and "styx-instances" in e["values"]:
                return False
            if e["operator"] == "In" and "styx-instances" not in e["values"]:
                return False
    return True


def test_no_world_egress_for_desktops():
    for d in _render(OVERLAY):
        if d["kind"] not in {"CiliumNetworkPolicy", "CiliumClusterwideNetworkPolicy"}:
            continue
        name = d["metadata"]["name"]
        sel = d["spec"].get("endpointSelector", {})
        if d["kind"] == "CiliumNetworkPolicy":
            if d["metadata"].get("namespace") not in (None, "styx-instances"):
                continue
            selects = True
        else:
            selects = _can_select_desktops(sel)
        if name in INFRA_ALLOWS:  # asserted, not exempted
            assert not selects, f"{name} must not select desktops"
            continue
        if not selects:
            continue
        for r in d["spec"].get("egress", []):
            assert not FORBIDDEN_EGRESS & r.keys(), name
            for p in r.get("toPorts", []):
                for port in p.get("ports", []):
                    assert port["port"] != "22", name
                    if port["protocol"] in {"UDP", "ANY"}:  # ANY includes UDP
                        assert port["protocol"] == "ANY" and port["port"] == "53" \
                            and "toEndpoints" in r, f"{name}: {port}"


def test_proxy_params_single_source():
    files = [p for p in COMPONENT.iterdir()
             if p.is_file() and p.suffix in {".yaml", ".yml", ".json"}]
    for needle in ("egress-proxy", "3128", "3129"):
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
    assert ing["toPorts"] == [{"ports": [{"port": "3128", "protocol": "TCP"},
                                         {"port": "3129", "protocol": "TCP"}]}]
    egress = c["spec"]["egress"]
    assert {"toEntities": ["world"], "toPorts": [{"ports": [
        {"port": "80", "protocol": "TCP"}, {"port": "443", "protocol": "TCP"}]}]} in egress
    assert any("toEndpoints" in r and r["toPorts"][0]["ports"][0]["port"] == "53"
               for r in egress)
    # local-config params must not leak into the rendered output
    assert not any(d["kind"] == "ConfigMap" and d["metadata"]["name"] == "proxy-params"
                   for d in docs)


# --- docs: control matrix + operator note (#61) ------------------------------
MATRIX = K8S.parents[1] / "docs" / "enterprise" / "control-matrix.md"


def test_control_matrix_points_at_component():
    rows = {line.split("|")[1].strip(): line for line in MATRIX.read_text().splitlines()
            if line.startswith("| ")}
    for cid in ("AC-4", "SC-7", "SC-7(5)"):
        row = rows[cid]
        assert "deploy/k8s/components/cilium-baseline/" in row, cid
        assert "patch-desktop-egress.yaml" in row, cid
        assert "implemented in code, not deployed" in row, cid
        assert "HAProxy part not done" in row, cid
        assert row.rstrip().endswith("| Planned |"), cid


def test_operator_note_covers_rollout():
    text = (COMPONENT / "README.md").read_text()
    for needle in ("policyAuditMode", "hubble observe --verdict AUDIT", "default-deny",
                   "toCIDR", "/32", "kubectl delete ccnp default-deny",
                   "| desktop | world 443 direct | denied |",
                   "| desktop | world SSH 22 | denied |",
                   "| desktop | any UDP except DNS | denied |",
                   "kube-apiserver", "break-glass", "styx.io/egress-mode", "3129"):
        assert needle in text, needle
    assert text.index("## Apply order") < text.index("## Audit-mode rollout")
    assert "enable audit mode first" in text
    rollback = text[text.index("## Rollback"):text.index("## Squid option B")]
    assert "partial" in rollback
    for name in ("allow-dns", "allow-webhooks", "squid-proxy", "CiliumClusterwideNetworkPolicy"):
        assert name in rollback, name
    assert "kubectl apply -f deploy/k8s/instances.yaml" in rollback
    assert "desktop-proxy-allowlist" in rollback and "desktop-proxy-category" in rollback
    squid = text[text.index("## Squid option B"):text.index("## Manual connectivity")]
    assert "replacement" in squid and "spec.egress.0.toPorts" in squid
    assert len(text.splitlines()) < 500
