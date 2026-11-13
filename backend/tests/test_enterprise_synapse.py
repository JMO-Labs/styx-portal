"""Static + render checks for deploy/enterprise/matrix (Synapse on CNPG, Keycloak OIDC)."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2] / "deploy/enterprise/matrix"
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


def _homeserver():
    return yaml.safe_load((ROOT / "config/homeserver.yaml").read_text())


def test_kustomization_lists_all_files():
    k = yaml.safe_load((ROOT / "kustomization.yaml").read_text())
    files = {p.relative_to(ROOT).as_posix() for p in ROOT.glob("*.yaml")
             if p.name != "kustomization.yaml"}
    assert set(k["resources"]) == files
    cm = k["configMapGenerator"][0]
    assert cm["name"] == "synapse-homeserver"
    assert any("config/homeserver.yaml" in f for f in cm["files"])


def test_namespace():
    (ns,) = of_kind("Namespace")
    assert ns["metadata"]["name"] == "matrix"
    assert ns["metadata"]["labels"]["styx.io/openbao-secrets"] == "true"
    assert ns["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"


def test_kustomize_build_and_kubeconform():
    _need("kustomize")
    out = subprocess.run(["kustomize", "build", str(ROOT)], capture_output=True,
                         text=True, check=True).stdout
    assert "kind: Deployment" in out
    _need("kubeconform")
    res = subprocess.run([str(ROOT.parents[2] / "scripts/k8s_policy_check.sh"), "--stdin"],
                         input=out, capture_output=True, text=True)
    assert res.returncode == 0, res.stdout + res.stderr


def test_deployment_pinned_and_hardened():
    (d,) = of_kind("Deployment")
    assert d["metadata"]["name"] == "synapse"
    spec = d["spec"]["template"]["spec"]
    (c,) = spec["containers"]
    assert DIGEST.search(c["image"])
    assert c["securityContext"]["allowPrivilegeEscalation"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    vols = {v["name"] for v in spec["volumes"]}
    assert {"config", "secrets", "oidc"} <= vols
    assert of_kind("Service")[0]["spec"]["ports"][0]["port"] == 8008
    (pdb,) = of_kind("PodDisruptionBudget")
    assert pdb["spec"]["selector"]["matchLabels"] == d["spec"]["selector"]["matchLabels"]


def test_db_cluster_c_collation_and_backup():
    (c,) = of_kind("Cluster")
    assert c["metadata"]["name"] == "synapse-db"
    init = c["spec"]["bootstrap"]["initdb"]
    assert init["localeCollate"] == "C" and init["localeCType"] == "C"
    assert init["encoding"] == "UTF8" and init["template"] == "template0"
    assert DIGEST.search(c["spec"]["imageName"])
    (os_,) = of_kind("ObjectStore")
    assert os_["spec"]["configuration"]["destinationPath"].endswith("synapse-db")
    (sb,) = of_kind("ScheduledBackup")
    assert sb["spec"]["cluster"]["name"] == "synapse-db"
    assert re.fullmatch(r"0 \d+ \d+ \* \* \*", sb["spec"]["schedule"])


def test_homeserver_oidc_only_no_federation():
    hs = _homeserver()
    (p,) = hs["oidc_providers"]
    assert p["idp_id"] == "keycloak"
    assert p["issuer"] == "https://login.example.internal/realms/styx"
    assert p["client_id"] == "synapse"
    assert p["client_secret_path"].startswith("/")
    assert "client_secret" not in p
    assert hs["password_config"]["enabled"] is False
    assert hs["enable_registration"] is False
    assert hs["federation_domain_whitelist"] == []
    assert hs["allow_public_rooms_over_federation"] is False
    assert hs["database"]["name"] == "psycopg2"
    assert hs["database"]["args"]["host"] == "synapse-db-rw"


def test_no_secret_values_in_git():
    text = "\n".join(p.read_text() for p in ROOT.rglob("*.yaml"))
    assert "macaroon_secret_key:" not in text
    assert "registration_shared_secret:" not in text
    assert not re.search(r"^\s*password:\s*(?!\"\{\{)\S", text, re.M)
    assert not [d for d in _docs() if d["kind"] == "Secret"]
    hs = _homeserver()
    assert "macaroon_secret_key_path" in hs and "registration_shared_secret_path" in hs
    assert "signing_key_path" in hs


def test_external_secrets():
    es = {d["metadata"]["name"]: d for d in of_kind("ExternalSecret")}
    oidc = es["synapse-oidc"]["spec"]
    assert oidc["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
    (item,) = oidc["data"]
    assert item["secretKey"] == "client-secret"
    assert item["remoteRef"]["key"] == "styx/synapse/oidc"
    sec = es["synapse-secrets"]["spec"]["data"]
    assert {i["secretKey"] for i in sec} >= {"macaroon", "registration", "signing.key"}
    assert all(i["remoteRef"]["key"] == "styx/synapse/secrets" for i in sec)
    assert "synapse-db-app" in es and "synapse-db-offsite" in es


def _policies():
    return {d["metadata"]["name"]: d for d in of_kind("CiliumNetworkPolicy")}


def test_default_deny_and_ingress():
    pol = _policies()
    deny = pol["synapse-default-deny"]["spec"]
    assert deny["endpointSelector"] == {} and deny["ingress"] == [{}] and deny["egress"] == [{}]
    ing = pol["synapse-ingress"]["spec"]["ingress"]
    nss = {r["fromEndpoints"][0]["matchLabels"]["k8s:io.kubernetes.pod.namespace"] for r in ing}
    assert nss == {"traefik", "styx"}


def test_egress_only_dns_db_keycloak():
    eg = _policies()["synapse-egress"]["spec"]["egress"]
    assert len(eg) == 3
    assert not any("toEntities" in r or "toCIDRSet" in r for r in eg)
    targets = [r["toEndpoints"][0]["matchLabels"] for r in eg]
    assert {"cnpg.io/cluster": "synapse-db"} in targets
    assert any(t.get("k8s-app") == "kube-dns" for t in targets)
    assert any(t.get("k8s:io.kubernetes.pod.namespace") == "keycloak" for t in targets)
