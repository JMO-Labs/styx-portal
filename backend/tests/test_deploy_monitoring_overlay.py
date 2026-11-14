"""Static checks for the deploy/monitoring kustomize overlay (kube-prometheus-stack)."""

import re
from pathlib import Path

import yaml

MON = Path(__file__).resolve().parents[2] / "deploy" / "monitoring"


def _load(name):
    return yaml.safe_load((MON / name).read_text())


def test_monitoring_chart_pinned():
    k = _load("kustomization.yaml")
    assert k["namespace"] == "monitoring"
    (chart,) = k["helmCharts"]
    assert chart["name"] == "kube-prometheus-stack"
    assert chart["repo"] == "oci://ghcr.io/prometheus-community/charts"
    assert re.fullmatch(r"87\.\d+\.\d+", str(chart["version"]))
    assert chart["releaseName"] == "kube-prometheus-stack"
    assert chart["namespace"] == "monitoring"
    assert chart["includeCRDs"] is False
    assert chart["valuesFile"] == "values.yaml"


def test_kustomization_lists_all_resources():
    k = _load("kustomization.yaml")
    assert "namespace.yaml" in k["resources"]
    ns = _load("namespace.yaml")
    assert ns["kind"] == "Namespace" and ns["metadata"]["name"] == "monitoring"
    for f in k["resources"]:
        assert (MON / f).is_file()


def test_values_airgapped():
    v = _load("values.yaml")
    assert v["global"]["imageRegistry"] == "harbor.example.invalid/proxy"
    assert v["global"]["imagePullSecrets"] == [{"name": "harbor-pull"}]
    assert v["grafana"]["plugins"] == []
    assert v["kubeProxy"]["enabled"] is False
    assert "gnetId" not in (MON / "values.yaml").read_text()
    p = v["prometheus"]["prometheusSpec"]
    assert p["retention"] == "15d"
    assert p["retentionSize"] == "45GB"
    assert p["replicas"] == 2
    assert p["ruleSelectorNilUsesHelmValues"] is False
    assert p["serviceMonitorSelectorNilUsesHelmValues"] is False
    pvc = p["storageSpec"]["volumeClaimTemplate"]["spec"]
    assert pvc["storageClassName"] == "longhorn-styx"
    assert pvc["resources"]["requests"]["storage"] == "50Gi"
    a = v["alertmanager"]["alertmanagerSpec"]
    assert a["replicas"] == 2
    assert a["storage"]["volumeClaimTemplate"]["spec"]["resources"]["requests"]["storage"]


def _walk(node, path=()):
    if isinstance(node, dict):
        for k, val in node.items():
            yield from _walk(val, (*path, str(k)))
    elif isinstance(node, list):
        for i, val in enumerate(node):
            yield from _walk(val, (*path, str(i)))
    else:
        yield path, node


def test_values_no_secrets():
    v = _load("values.yaml")
    assert v["grafana"]["admin"]["existingSecret"]
    for path, val in _walk(v):
        key = path[-1].lower()
        if ("password" in key or "secret" in key) and isinstance(val, str) and val:
            assert "existingsecret" in key or key.endswith("secretname"), path
