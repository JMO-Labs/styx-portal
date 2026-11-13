"""Static + render checks for deploy/enterprise/wikijs (issue #275)."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy/enterprise/wikijs"
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
    assert {"namespace.yaml", "deployment.yaml", "pdb.yaml"} <= set(res)


def test_kustomize_build_and_kubeconform():
    _need("kustomize")
    out = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True,
                         text=True, check=True).stdout
    assert "kind: Deployment" in out
    _need("kubeconform")
    res = subprocess.run([str(ROOT.parents[2] / "scripts/k8s_policy_check.sh"), "--stdin"],
                         input=out, capture_output=True, text=True, check=False)
    assert res.returncode == 0, res.stdout + res.stderr


def test_namespace():
    (ns,) = of_kind("Namespace")
    assert ns["metadata"]["name"] == "wikijs"
    assert ns["metadata"]["labels"]["styx.io/openbao-secrets"] == "true"
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_db_cluster_and_backup():
    (c,) = of_kind("Cluster")
    spec = c["spec"]
    assert c["metadata"]["name"] == "wikijs-db"
    assert DIGEST.search(spec["imageName"])
    (plugin,) = spec["plugins"]
    assert plugin["name"] == "barman-cloud.cloudnative-pg.io" and plugin["isWALArchiver"]
    (store,) = of_kind("ObjectStore")
    assert plugin["parameters"]["barmanObjectName"] == store["metadata"]["name"]
    (sb,) = of_kind("ScheduledBackup")
    assert sb["spec"]["cluster"]["name"] == "wikijs-db"
    assert sb["spec"]["schedule"].split()[3:] == ["*", "*", "*"]   # daily


def test_no_plain_secret_with_data():
    for s in of_kind("Secret"):
        assert not s.get("data") and not s.get("stringData")


def test_oidc_external_secret():
    ess = {d["metadata"]["name"]: d for d in of_kind("ExternalSecret")}
    es = ess["wikijs-oidc"]
    assert es["spec"]["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    (item,) = es["spec"]["data"]
    assert item["secretKey"] == "client-secret"
    assert item["remoteRef"] == {"key": "kv/styx/wikijs/oidc", "property": "client_secret"}


def test_oidc_secret_matches_keycloak_side():
    kc = ROOT.parent / "keycloak/external-secrets.yaml"
    kcs = {d["metadata"]["name"]: d for d in yaml.safe_load_all(kc.read_text()) if d}
    (kc_item,) = kcs["keycloak-wikijs-oidc"]["spec"]["data"]
    ours = {d["metadata"]["name"]: d for d in of_kind("ExternalSecret")}
    (item,) = ours["wikijs-oidc"]["spec"]["data"]
    assert item["remoteRef"] == kc_item["remoteRef"]


def test_every_used_secret_comes_from_external_secret():
    (d,) = of_kind("Deployment")
    used = {e["valueFrom"]["secretKeyRef"]["name"]
            for c in d["spec"]["template"]["spec"]["containers"]
            for e in c.get("env", []) if "secretKeyRef" in e.get("valueFrom", {})}
    (c,) = of_kind("Cluster")
    used.add(c["spec"]["bootstrap"]["initdb"]["secret"]["name"])
    (o,) = of_kind("ObjectStore")
    used |= {v["name"] for v in o["spec"]["configuration"]["s3Credentials"].values()}
    targets = {es["spec"]["target"]["name"] for es in of_kind("ExternalSecret")}
    assert "wikijs-oidc" in used
    cnpg_owned = {"wikijs-db-ca"}  # created by CNPG, not ESO
    assert used - cnpg_owned <= targets, used - cnpg_owned - targets


def test_deployment_oidc_only():
    (d,) = of_kind("Deployment")
    pod = d["spec"]["template"]["spec"]
    (ctr,) = pod["containers"]
    assert DIGEST.search(ctr["image"])
    env = {e["name"]: e for e in ctr["env"]}
    assert env["DB_HOST"]["value"] == "wikijs-db-rw"
    assert "secretKeyRef" in env["DB_PASS"]["valueFrom"]
    assert env["DB_SSL"]["value"] == "true"
    assert env["DB_SSL_CA"]["valueFrom"]["secretKeyRef"] == {"name": "wikijs-db-ca", "key": "ca.crt"}
    assert "secretKeyRef" in env["OIDC_CLIENT_SECRET"]["valueFrom"]
    assert env["OIDC_CLIENT_ID"]["value"] == "wikijs"
    assert re.fullmatch(r"https://login\.[^/]+/realms/styx", env["OIDC_ISSUER"]["value"])
    assert env["LOCAL_LOGIN_DISABLED"]["value"] == "true"
    if d["spec"]["replicas"] > 1:
        assert env["HA_ACTIVE"]["value"] == "true"
    mounts = {m["mountPath"]: m["name"] for m in ctr["volumeMounts"]}
    assert mounts["/wiki/data"] == "data"
    base = "http://keycloak.keycloak.svc:8080/realms/styx/protocol/openid-connect"
    assert env["OIDC_TOKEN_URL"]["value"] == f"{base}/token"
    assert env["OIDC_USERINFO_URL"]["value"] == f"{base}/userinfo"
    sc = ctr["securityContext"]
    assert sc["runAsNonRoot"] and sc["allowPrivilegeEscalation"] is False
    assert "OIDC" in (ROOT / "deployment.yaml").read_text().split("apiVersion")[0]


def test_keycloak_accepts_wikijs_on_8080():
    kc = ROOT.parent / "keycloak/networkpolicy.yaml"
    found = False
    for d in yaml.safe_load_all(kc.read_text()):
        if not d or d["metadata"]["name"] != "keycloak-ingress-from-traefik":
            continue
        for r in d["spec"]["ingress"]:
            for fe in r.get("fromEndpoints", []):
                ml = fe["matchLabels"]
                if (
                    ml.get("k8s:io.kubernetes.pod.namespace") == "wikijs"
                    and ml.get("app.kubernetes.io/name") == "wikijs"
                ):
                    ports = [p for t in r["toPorts"] for p in t["ports"]]
                    assert {"port": "8080", "protocol": "TCP"} in ports
                    found = True
    assert found


def test_pdb_matches_pods():
    (pdb,) = of_kind("PodDisruptionBudget")
    (d,) = of_kind("Deployment")
    sel = pdb["spec"]["selector"]["matchLabels"]
    assert sel.items() <= d["spec"]["template"]["metadata"]["labels"].items()


def test_service_selects_pods():
    (svc,) = of_kind("Service")
    (d,) = of_kind("Deployment")
    assert svc["spec"]["selector"].items() <= d["spec"]["template"]["metadata"]["labels"].items()


def _rules(direction):
    out = []
    for c in of_kind("CiliumNetworkPolicy"):
        for r in c["spec"].get(direction, []):
            out.append((c["spec"]["endpointSelector"], r))
    return out


def test_network_policies():
    cnps = of_kind("CiliumNetworkPolicy")
    assert any(c["metadata"]["name"] == "wikijs-default-deny" for c in cnps)
    text = json.dumps(cnps)
    for needle in ("traefik", "wikijs-db", "kube-dns", "keycloak"):
        assert needle in text
    # no world egress for the app
    assert "world" not in text and "0.0.0.0" not in text
    app_egress = [r for sel, r in _rules("egress")
                  if sel.get("matchLabels", {}).get("app.kubernetes.io/name") == "wikijs"]
    ports = {p["port"] for r in app_egress for tp in r.get("toPorts", []) for p in tp["ports"]}
    assert ports == {"5432", "53", "8080"}
    app_ingress = [r for sel, r in _rules("ingress")
                   if sel.get("matchLabels", {}).get("app.kubernetes.io/name") == "wikijs" and r]
    for r in app_ingress:
        (peer,) = r["fromEndpoints"]
        assert peer["matchLabels"]["k8s:io.kubernetes.pod.namespace"] == "traefik"
