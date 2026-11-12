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
    if os.environ.get("REQUIRE_" + tool.upper()) == "1":
        pytest.fail(f"{tool} required but not installed")
    pytest.skip(f"{tool} not installed")


def test_kustomization_lists_all_files():
    res = yaml.safe_load((ROOT / "kustomization.yaml").read_text())["resources"]
    files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*.yaml")
             if p.name != "kustomization.yaml"}
    assert set(res) == files


def test_kustomize_build_and_kubeconform():
    _need("kustomize")
    out = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True,
                         text=True, check=True).stdout
    assert "kind: Deployment" in out
    _need("kubeconform")
    # Vendored CRD schemas + explicit SKIP list; no blanket ignore of unknown kinds.
    res = subprocess.run([str(ROOT.parents[2] / "scripts/k8s_policy_check.sh"), "--stdin"],
                         input=out, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


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
    assert {"keycloak-admin", "keycloak-db-app", "keycloak-db-offsite"} <= set(ess)
    for es in ess.values():
        assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    assert "kv/keycloak/admin" in json.dumps(ess["keycloak-admin"])


def _used_secret_names():
    (d,) = of_kind("Deployment")
    names = {e["valueFrom"]["secretKeyRef"]["name"]
             for c in d["spec"]["template"]["spec"]["containers"]
             for e in c.get("env", []) if "secretKeyRef" in e.get("valueFrom", {})}
    (c,) = of_kind("Cluster")
    names.add(c["spec"]["bootstrap"]["initdb"]["secret"]["name"])
    for o in of_kind("ObjectStore"):
        names |= {v["name"] for v in o["spec"]["configuration"]["s3Credentials"].values()}
    return names


def test_every_used_secret_comes_from_external_secret():
    targets = {es["spec"]["target"]["name"] for es in of_kind("ExternalSecret")}
    used = _used_secret_names()
    assert {"keycloak-admin", "keycloak-db-app", "keycloak-db-offsite"} <= used
    assert used <= targets, used - targets


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


def _db_rules(direction, peer_key):
    out = []
    for c in of_kind("CiliumNetworkPolicy"):
        sel = c["spec"].get("endpointSelector", {}).get("matchLabels", {})
        if sel.get("cnpg.io/cluster") != "keycloak-db":
            continue
        for r in c["spec"].get(direction, []):
            peers = r.get(peer_key, [])
            if any(p.get("matchLabels", {}).get("cnpg.io/cluster") == "keycloak-db" for p in peers):
                out += [p["port"] for tp in r.get("toPorts", []) for p in tp["ports"]]
    return out


def test_db_replication_between_instances():
    assert "5432" in _db_rules("ingress", "fromEndpoints")
    assert "5432" in _db_rules("egress", "toEndpoints")


def test_prometheus_scrape_allowed():
    ports = set()
    for c in of_kind("CiliumNetworkPolicy"):
        for r in c["spec"].get("ingress", []):
            for f in r.get("fromEndpoints", []):
                if f.get("matchLabels", {}).get("k8s:io.kubernetes.pod.namespace") == "monitoring":
                    ports |= {p["port"] for tp in r["toPorts"] for p in tp["ports"]}
    assert {"9000", "9187"} <= ports
