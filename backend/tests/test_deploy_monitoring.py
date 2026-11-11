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


K8S = Path(__file__).resolve().parents[2] / "deploy" / "k8s"


def _k8s_docs(name):
    return list(yaml.safe_load_all((K8S / name).read_text()))


def _k8s_by_kind(name, kind, obj_name=None):
    for d in _k8s_docs(name):
        if d and d["kind"] == kind and (obj_name is None or d["metadata"]["name"] == obj_name):
            return d
    raise AssertionError(f"{kind} {obj_name} not in {name}")


def test_backend_exposes_metrics_port():
    dep = _k8s_by_kind("backend.yaml", "Deployment")
    ports = dep["spec"]["template"]["spec"]["containers"][0]["ports"]
    assert {"name": "metrics", "containerPort": 9000} in ports
    svc = _k8s_by_kind("backend.yaml", "Service", "backend")
    assert svc["metadata"]["labels"]["app"] == "styx-backend"
    assert any(p["name"] == "metrics" and p["port"] == 9000 for p in svc["spec"]["ports"])
    assert _k8s_by_kind("configmap.yaml", "ConfigMap")["data"]["METRICS_PORT"] == "9000"


def test_servicemonitor_matches_backend_service():
    sm = _k8s_by_kind("servicemonitor.yaml", "ServiceMonitor")
    svc = _k8s_by_kind("backend.yaml", "Service", "backend")
    assert sm["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    sel = sm["spec"]["selector"]["matchLabels"]
    assert all(svc["metadata"]["labels"].get(k) == v for k, v in sel.items())
    assert sm["spec"]["namespaceSelector"]["matchNames"] == ["styx"]
    (ep,) = sm["spec"]["endpoints"]
    assert ep["port"] == "metrics"
    assert ep["interval"] == "30s"
    assert any(p["name"] == "metrics" for p in svc["spec"]["ports"])


def test_metrics_networkpolicy_only_monitoring():
    np = _k8s_by_kind("networkpolicy.yaml", "NetworkPolicy", "backend-metrics-ingress")
    assert np["spec"]["podSelector"]["matchLabels"] == {"app": "styx-backend"}
    (rule,) = np["spec"]["ingress"]
    assert rule["ports"] == [{"port": 9000, "protocol": "TCP"}]
    (peer,) = rule["from"]
    assert peer == {
        "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "monitoring"}}
    }
    for d in _k8s_docs("networkpolicy.yaml"):
        if d["metadata"]["name"] == "backend-ingress":
            assert all(p["port"] != 9000 for r in d["spec"]["ingress"] for p in r["ports"])
    deny = _k8s_by_kind("networkpolicy.yaml", "NetworkPolicy", "default-deny-ingress")
    assert deny["spec"] == {"podSelector": {}, "policyTypes": ["Ingress"]}


def test_k8s_kustomization_lists_all_resources():
    res = _k8s_by_kind("kustomization.yaml", "Kustomization")["resources"]
    assert "servicemonitor.yaml" in res
    assert "prometheusrule.yaml" in res
    rule = _k8s_by_kind("prometheusrule.yaml", "PrometheusRule")
    assert rule["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    for r in res:
        assert (K8S / r).exists(), r
