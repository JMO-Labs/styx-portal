"""Static checks for backend metrics wiring in deploy/k8s."""

from pathlib import Path

import yaml


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




def test_k8s_kustomization_lists_servicemonitor():
    res = _k8s_by_kind("kustomization.yaml", "Kustomization")["resources"]
    assert "servicemonitor.yaml" in res
    for r in res:
        assert (K8S / r).exists(), r
