"""Static checks for deploy/enterprise/element (issue #278): SSO-only Element Web."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy/enterprise/element"
FILES = ("deployment.yaml", "service.yaml", "pdb.yaml", "configmap.yaml", "networkpolicy.yaml")


def docs():
    out = {}
    for name in FILES:
        for d in yaml.safe_load_all((ROOT / name).read_text()):
            if d:
                out[(d["kind"], d["metadata"]["name"])] = d
    return out


def config():
    return json.loads(docs()[("ConfigMap", "element-config")]["data"]["config.json"])


def test_kustomization_lists_resources():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    assert set(k["resources"]) == set(FILES)
    assert k.get("namespace", "matrix") == "matrix"


def test_namespace_not_redefined():
    assert not any(k[0] == "Namespace" for k in docs())
    assert not (ROOT / "namespace.yaml").exists()


def test_all_objects_in_matrix_namespace():
    for (_, name), d in docs().items():
        assert d["metadata"]["namespace"] == "matrix", name


def test_deployment_pinned_and_nonroot():
    d = docs()[("Deployment", "element")]
    spec = d["spec"]["template"]["spec"]
    assert re.search(r"@sha256:[0-9a-f]{64}$", spec["containers"][0]["image"])
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert spec["securityContext"]["runAsUser"] != 0
    assert spec["containers"][0]["securityContext"]["allowPrivilegeEscalation"] is False
    c = spec["containers"][0]
    env = {e["name"]: e["value"] for e in c["env"]}
    port = c["ports"][0]["containerPort"]
    assert int(env["ELEMENT_WEB_PORT"]) == port > 1024
    mounts = {m["mountPath"] for m in c["volumeMounts"]}
    assert {"/etc/nginx/conf.d", "/var/cache/nginx"} <= mounts


def test_service_and_pdb_select_deployment():
    d = docs()
    labels = d[("Deployment", "element")]["spec"]["template"]["metadata"]["labels"]
    assert d[("Service", "element")]["spec"]["selector"].items() <= labels.items()
    assert d[("PodDisruptionBudget", "element")]["spec"]["selector"]["matchLabels"].items() <= labels.items()


def test_config_json_sso_only():
    c = config()
    assert c["default_server_config"]["m.homeserver"]["base_url"].startswith("https://matrix.")
    assert c["disable_custom_urls"] is True
    assert c["disable_guests"] is True
    assert c["sso_redirect_options"]["immediate"] is True


def test_config_mounted_into_deployment():
    spec = docs()[("Deployment", "element")]["spec"]["template"]["spec"]
    assert any(v.get("configMap", {}).get("name") == "element-config" for v in spec["volumes"])
    mounts = spec["containers"][0]["volumeMounts"]
    assert any(m["mountPath"] == "/app/config.json" and m.get("subPath") == "config.json" for m in mounts)


def test_networkpolicy_ingress_controller_only_and_dns_egress():
    np = docs()[("NetworkPolicy", "element")]["spec"]
    assert set(np["policyTypes"]) == {"Ingress", "Egress"}
    assert len(np["ingress"]) == 1
    frm = np["ingress"][0]["from"]
    assert len(frm) == 1
    assert frm[0]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "traefik"}
    assert np["egress"]
    for rule in np["egress"]:
        assert {(p["port"], p["protocol"]) for p in rule["ports"]} <= {(53, "UDP"), (53, "TCP")}
        assert rule["to"][0]["namespaceSelector"]["matchLabels"] == {"kubernetes.io/metadata.name": "kube-system"}


@pytest.mark.skipif(not shutil.which("kustomize"), reason="kustomize absent")
def test_kustomize_build_and_kubeconform():
    out = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True, text=True, check=True).stdout
    assert "kind: Deployment" in out
    if shutil.which("kubeconform"):
        subprocess.run(["kubeconform", "-strict", "-summary", "-"], input=out, text=True, check=True)
