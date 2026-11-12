"""Static checks for deploy/enterprise/banner (issue #132, ADR-0027/0049)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy/enterprise/banner"


def docs():
    out = {}
    for name in ("namespace.yaml", "deployment.yaml", "service.yaml",
                 "networkpolicy.yaml", "ingressroute.yaml", "configmap.yaml"):
        for d in yaml.safe_load_all((ROOT / name).read_text()):
            if d:
                out[(d["kind"], d["metadata"]["name"])] = d
    return out


def html():
    cm = docs()[("ConfigMap", "banner-site")]
    return cm["data"]


def test_kustomization_lists_resources():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    for f in ("namespace.yaml", "deployment.yaml", "service.yaml",
              "networkpolicy.yaml", "ingressroute.yaml", "configmap.yaml"):
        assert f in k["resources"]


def test_deployment_hardened_and_pinned():
    dep = docs()[("Deployment", "banner")]
    spec = dep["spec"]["template"]["spec"]
    c = spec["containers"][0]
    assert "nginx-unprivileged" in c["image"]
    assert re.search(r"@sha256:[0-9a-f]{64}$", c["image"])
    assert c["securityContext"]["readOnlyRootFilesystem"] is True
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True


def test_networkpolicy_present_ingress_from_traefik_only():
    np = docs()[("CiliumNetworkPolicy", "banner-ingress-from-traefik")]
    frm = np["spec"]["ingress"][0]["fromEndpoints"][0]["matchLabels"]
    assert frm["k8s:io.kubernetes.pod.namespace"] == "traefik"


def test_route_has_no_client_auth():
    route = docs()[("IngressRoute", "banner")]
    text = (ROOT / "ingressroute.yaml").read_text()
    assert "clientAuth" not in text and "TLSOption" not in text
    tls = route["spec"].get("tls", {})
    assert "options" not in tls
    assert "banner." in route["spec"]["routes"][0]["match"]
    assert "login." not in route["spec"]["routes"][0]["match"]


def test_page_banner_agree_and_decline():
    data = html()
    page = data["index.html"]
    assert "You are accessing a U.S. Government" in page
    assert 'id="agree"' in page and "I agree" in page
    assert "/start" in page  # configurable login start URL
    conf = data["nginx.conf"]
    m = re.search(r"location = /start \{[^}]*?return 30\d\s+(\S+?);", conf, re.S)
    assert m and re.search(r"/api/auth/oauth/[^/]+/start$", m.group(1))
    assert "declined" in page.lower()
    # decline path shows no link
    assert "<a " not in data["declined.html"]


def test_no_external_resources_and_csp():
    data = html()
    for name in ("index.html", "declined.html"):
        assert not re.search(r'(src|href)="https?://', data[name])
        assert "<script src" not in data[name]
    assert "default-src 'self'" in data["nginx.conf"]
    assert "Content-Security-Policy" in data["nginx.conf"]


def _require(tool):
    if shutil.which(tool):
        return
    if os.environ.get("REQUIRE_KUSTOMIZE") == "1" or os.environ.get("REQUIRE_KUBECONFORM") == "1":
        pytest.fail(f"{tool} required but not installed")
    pytest.skip(f"{tool} not installed")


def _build():
    _require("kustomize")
    r = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_kustomize_build():
    _build()


def test_kubeconform_strict():
    out = _build()
    _require("kubeconform")
    script = ROOT.parents[2] / "scripts/k8s_policy_check.sh"
    r = subprocess.run([str(script), "--stdin"], input=out, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_policy_check_targets_banner():
    script = (ROOT.parents[2] / "scripts/k8s_policy_check.sh").read_text()
    assert "deploy/enterprise/banner" in script


def test_nginx_conf_not_in_web_root():
    vol = next(v for v in docs()[("Deployment", "banner")]["spec"]["template"]["spec"]["volumes"]
               if v["name"] == "site")
    items = vol["configMap"]["items"]
    assert sorted(i["path"] for i in items) == ["declined.html", "index.html", "styles.css"]
    assert all(i["key"] == i["path"] for i in items)
