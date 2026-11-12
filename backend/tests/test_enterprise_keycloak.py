"""Static + render checks for deploy/enterprise/keycloak (issue #128, ADR-0014)."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy/enterprise/keycloak"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")


def _docs():
    out = []
    for p in sorted(ROOT.glob("*.yaml")):
        if p.name != "kustomization.yaml":
            out += [d for d in yaml.safe_load_all(p.read_text()) if d]
    return out


def of_kind(kind):
    return [d for d in _docs() if d["kind"] == kind]


def _need(tool):
    if shutil.which(tool):
        return
    if os.environ.get("REQUIRE_KUSTOMIZE") == "1":
        pytest.fail(f"{tool} required but not installed")
    pytest.skip(f"{tool} not installed")


def test_kustomization_lists_all_files():
    res = yaml.safe_load((ROOT / "kustomization.yaml").read_text())["resources"]
    files = {p.name for p in ROOT.glob("*.yaml") if p.name != "kustomization.yaml"}
    assert set(res) == files


def test_kustomize_build_and_kubeconform():
    _need("kustomize")
    out = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True,
                         text=True, check=True).stdout
    assert "kind: Deployment" in out
    _need("kubeconform")
    subprocess.run(["kubeconform", "-strict", "-summary", "-ignore-missing-schemas"],
                   input=out, text=True, check=True)


def test_db_cluster():
    (c,) = of_kind("Cluster")
    spec = c["spec"]
    assert c["metadata"]["name"] == "keycloak-db" and spec["instances"] == 2
    assert DIGEST.search(spec["imageName"])
    aff = spec["affinity"]
    assert aff["enablePodAntiAffinity"] is True and aff["podAntiAffinityType"] == "required"
    (plugin,) = spec["plugins"]
    assert plugin["name"] == "barman-cloud.cloudnative-pg.io" and plugin["isWALArchiver"]
    names = {d["metadata"]["name"] for d in of_kind("ObjectStore")}
    assert plugin["parameters"]["barmanObjectName"] in names
    assert of_kind("ScheduledBackup")


def test_no_plain_secret_with_data():
    for s in of_kind("Secret"):
        assert not s.get("data") and not s.get("stringData"), s["metadata"]["name"]


def test_external_secrets():
    ess = {d["metadata"]["name"]: d for d in of_kind("ExternalSecret")}
    assert {"keycloak-admin", "keycloak-db-offsite"} <= set(ess)
    for es in ess.values():
        assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    assert "kv/keycloak/admin" in json.dumps(ess["keycloak-admin"])


def test_deployment():
    (d,) = of_kind("Deployment")
    assert d["spec"]["replicas"] >= 2
    pod = d["spec"]["template"]["spec"]
    (ctr,) = pod["containers"]
    assert DIGEST.search(ctr["image"])
    env = {e["name"]: e for e in ctr["env"]}
    assert env["KC_HEALTH_ENABLED"]["value"] == "true"
    assert env["KC_METRICS_ENABLED"]["value"] == "true"
    assert env["KC_PROXY_HEADERS"]["value"] in ("xforwarded", "forwarded")
    assert env["KC_DB_URL_HOST"]["value"] == "keycloak-db-rw"
    # all credentials via secretKeyRef, never inline
    for n in ("KC_BOOTSTRAP_ADMIN_PASSWORD", "KC_DB_PASSWORD"):
        assert "secretKeyRef" in env[n]["valueFrom"], n
    assert pod["affinity"]["podAntiAffinity"]["requiredDuringSchedulingIgnoredDuringExecution"]
    sc = ctr["securityContext"]
    assert sc["runAsNonRoot"] and sc["allowPrivilegeEscalation"] is False


def test_pdb_matches_pods():
    (pdb,) = of_kind("PodDisruptionBudget")
    (d,) = of_kind("Deployment")
    assert pdb["spec"]["maxUnavailable"] == 1
    sel = pdb["spec"]["selector"]["matchLabels"]
    assert sel.items() <= d["spec"]["template"]["metadata"]["labels"].items()


def test_namespace_labels():
    (ns,) = of_kind("Namespace")
    assert ns["metadata"]["labels"]["styx.io/openbao-secrets"] == "true"
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_network_policies():
    cnps = of_kind("CiliumNetworkPolicy")
    text = json.dumps(cnps)
    assert "traefik" in text and "keycloak-db" in text and "kube-dns" in text
    assert any(c["metadata"]["name"] == "keycloak-default-deny" for c in cnps)
    ports = {p["port"] for c in cnps for r in c["spec"].get("egress", [])
             for tp in r.get("toPorts", []) for p in tp["ports"]}
    assert {"5432", "53", "80", "443"} <= ports
