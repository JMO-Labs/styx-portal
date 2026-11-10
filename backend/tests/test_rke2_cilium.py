"""Static checks for the rke2-cilium HelmChartConfig under deploy/rke2 (issue #18)."""

import re

import jinja2
import pytest
import yaml

from tests.test_rke2_iac import ROOT, _tracked_files, _vars

# Not *.j2: the role templates into server/manifests/ under the source basename,
# and RKE2 only applies .yaml/.yml/.json files there.
TEMPLATE = "templates/rke2-cilium.yaml"
METRICS = [
    "dns",
    "drop:sourceContext=namespace;destinationContext=namespace",
    "flow:sourceContext=namespace;destinationContext=namespace",
    "tcp",
    "icmp",
    "port-distribution",
]


def _render(**overrides):
    ctx = {**_vars("all"), **overrides}
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - YAML, not HTML
    doc = yaml.safe_load(env.from_string((ROOT / TEMPLATE).read_text()).render(ctx))
    return doc, yaml.safe_load(doc["spec"]["valuesContent"])


def test_template_and_vars_exist():
    assert (ROOT / TEMPLATE).is_file()
    v = _vars("all")
    assert v["cilium_kube_proxy_replacement"] is True
    assert v["cilium_encryption_type"] == "wireguard"


def test_template_name_is_applied_by_rke2():
    assert TEMPLATE.endswith((".yaml", ".yml", ".json"))


def test_raw_template_is_valid_yaml():
    # yamllint and ansible-lint parse the unrendered file too.
    assert yaml.safe_load((ROOT / TEMPLATE).read_text())["kind"] == "HelmChartConfig"


def test_disable_kube_proxy_tied_to_kpr():
    assert _vars("all")["disable_kube_proxy"] == "{{ cilium_kube_proxy_replacement }}"


def test_manifest_shipped_to_servers():
    assert any(m.endswith(TEMPLATE) for m in _vars("masters")["rke2_custom_manifests"])
    assert "rke2_custom_manifests" not in _vars("workers")


def test_helmchartconfig_header():
    doc, _ = _render()
    assert doc["apiVersion"] == "helm.cattle.io/v1"
    assert doc["kind"] == "HelmChartConfig"
    assert doc["metadata"] == {"name": "rke2-cilium", "namespace": "kube-system"}
    assert isinstance(doc["spec"]["valuesContent"], str)


def test_kpr_on_uses_localhost():
    _, v = _render()
    assert v["kubeProxyReplacement"] is True
    assert v["k8sServiceHost"] == "localhost"
    assert v["k8sServicePort"] == "6443"
    assert v["bpf"]["masquerade"] is True
    assert v["k8sServiceHost"] not in _vars("all")["rke2_additional_sans"]


def test_kpr_off_omits_service_host():
    _, v = _render(cilium_kube_proxy_replacement=False)
    assert v["kubeProxyReplacement"] is False
    assert "k8sServiceHost" not in v
    assert "k8sServicePort" not in v


@pytest.mark.parametrize(("kind", "expected"), [
    ("wireguard", {"enabled": True, "type": "wireguard", "nodeEncryption": False}),
    ("ipsec", {"enabled": True, "type": "ipsec", "ipsec": {"secretName": "cilium-ipsec-keys"}}),
    ("none", {"enabled": False}),
])
def test_encryption_variants(kind, expected):
    _, v = _render(cilium_encryption_type=kind)
    assert v["encryption"] == expected


def test_encryption_invalid_value_breaks_render():
    try:
        _, v = _render(cilium_encryption_type="aes")
    except Exception:  # noqa: BLE001 - any render failure is acceptable
        return
    assert not isinstance(v["encryption"]["enabled"], bool)


def test_metrics_and_hubble():
    _, v = _render()
    assert v["prometheus"]["enabled"] is True
    assert v["prometheus"]["metricsService"] is True
    assert v["operator"]["prometheus"]["enabled"] is True
    h = v["hubble"]
    assert h["enabled"] is True
    assert h["relay"]["enabled"] is True
    assert h["ui"]["enabled"] is False
    assert h["metrics"]["enableOpenMetrics"] is True
    assert h["metrics"]["enabled"] == METRICS


def test_no_pod_level_metric_context():
    _, v = _render()
    assert not [m for m in v["hubble"]["metrics"]["enabled"] if "pod" in m]


def _walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.values():
            yield from _walk(child)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child)


@pytest.mark.parametrize("kind", ["wireguard", "ipsec", "none"])
def test_no_servicemonitors_enabled(kind):
    _, v = _render(cilium_encryption_type=kind)
    for d in _walk(v):
        assert (d.get("serviceMonitor") or {}).get("enabled") is not True
        assert d.get("trustCRDsExist") is not True


IPSEC_KEY = re.compile(r"rfc4106\(|kind:\s*Secret\b|^\s*keys:\s*\S*[0-9a-f]{16}", re.I | re.M)


def test_ipsec_key_regex_catches_planted_values():
    assert IPSEC_KEY.search("keys: 3+ rfc4106(gcm(aes)) abc 128")
    assert IPSEC_KEY.search("kind: Secret")
    assert IPSEC_KEY.search("  keys: 0123456789abcdef0123")
    assert not IPSEC_KEY.search("secretName: cilium-ipsec-keys")


def test_no_ipsec_key_material():
    bad = [str(p.relative_to(ROOT)) for p in _tracked_files()
           if IPSEC_KEY.search(p.read_text())]
    assert not bad
