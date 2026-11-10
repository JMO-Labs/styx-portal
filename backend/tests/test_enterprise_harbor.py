"""Static checks for deploy/enterprise/harbor (issue #5)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from tests import harbor_checks as hc

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "deploy/enterprise/harbor"
CHART = ROOT / "charts/harbor-1.19.4.tgz"
FIXTURES = Path(__file__).parent / "fixtures/harbor_bad"
HA = hc.HA_COMPONENTS


def values():
    return yaml.safe_load((ROOT / "values.yaml").read_text())


def manifest_files():
    skip = {"values.yaml", "kustomization.yaml"}
    return sorted(p for p in ROOT.glob("*.yaml") if p.name not in skip)


def manifests():
    """Every doc under harbor/*.yaml (except values/kustomization) by (kind, name)."""
    out = {}
    for path in manifest_files():
        for d in yaml.safe_load_all(path.read_text()):
            if d:
                out[(d["kind"], d["metadata"]["name"])] = d
    return out


def of_kind(kind):
    return [d for (k, _), d in manifests().items() if k == kind]


def test_layout():
    for name in ("values.yaml", "kustomization.yaml", "README.md", "harbor_bootstrap.py"):
        assert (ROOT / name).is_file(), name
    readme = (ROOT / "README.md").read_text()
    for s in ("1.19.4", "2.15.4", "harbor.example.internal", "helm template"):
        assert s in readme, s


def test_kustomization_lists_all_files():
    resources = yaml.safe_load((ROOT / "kustomization.yaml").read_text())["resources"]
    assert sorted(resources) == sorted(p.name for p in manifest_files())
    for r in resources:
        assert (ROOT / r).is_file(), r


def test_images_pinned_by_digest():
    refs = list(hc.image_refs(values()))
    assert len(refs) >= 9
    assert hc.check_images(values()) == []
    db = manifests()[("Cluster", "harbor-db")]
    assert hc.DIGEST_REF.match(db["spec"]["imageName"])


def test_external_db_verify_full():
    v = values()
    assert hc.check_database(v) == []
    ext = v["database"]["external"]
    assert ext["host"] == "harbor-db-rw.harbor.svc" and str(ext["port"]) == "5432"


def test_s3_storage():
    assert hc.check_storage(values()) == []


def test_ha_replicas():
    v = values()
    assert hc.check_ha(v) == []
    assert v["redis"]["type"] == "internal"


def test_trivy_disabled_internal_tls_off_metrics_on():
    assert hc.check_toggles(values()) == []


def test_no_default_secrets():
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".yaml", ".md", ".py"}:
            text = path.read_text()
            docs = list(yaml.safe_load_all(text)) if path.suffix == ".yaml" else []
            assert hc.leaks(text, docs) == [], path
    text = (ROOT / "values.yaml").read_text()
    assert not [ln for ln in text.splitlines()
                if ln.strip().startswith("password:") and ln.split(":", 1)[1].strip()]
    # the checker is not vacuous
    bad = (FIXTURES / "leaky.yaml").read_text()
    assert len(hc.leaks(bad, list(yaml.safe_load_all(bad)))) >= 2
    assert hc.leaks("-----BEGIN " + "RSA PRIVATE KEY-----")


def test_existing_secrets_only():
    assert hc.check_secrets(values()) == []


def test_auth_settings():
    assert hc.check_auth(values()) == []
    cfg = json.loads(values()["core"]["configureUserSettings"])
    assert cfg["auth_mode"] == "db_auth" and cfg["self_registration"] is False


def test_ingress_internal_only():
    v = values()
    assert hc.check_expose(v) == []
    assert v["expose"]["ingress"]["className"] == "traefik"
    assert v["expose"]["tls"]["secret"]["secretName"] == "harbor-tls"
    assert v["externalURL"] == "https://harbor.example.internal"
    assert v["caSecretName"] == "harbor-tls"  # else core's ca-download volume has no name


def test_security_context_restricted():
    sc = values()["containerSecurityContext"]
    assert sc["runAsNonRoot"] is True and sc["allowPrivilegeEscalation"] is False
    assert sc["capabilities"]["drop"] == ["ALL"]
    assert sc["seccompProfile"]["type"] == "RuntimeDefault"


def test_namespace_labels():
    ns = manifests()[("Namespace", "harbor")]
    labels = ns["metadata"]["labels"]
    assert labels["styx.io/openbao-secrets"] == "true"
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"


def test_harbor_db_cluster():
    m = manifests()
    spec = m[("Cluster", "harbor-db")]["spec"]
    assert spec["instances"] == 2
    assert spec["bootstrap"]["initdb"] == {"database": "registry", "owner": "harbor"}
    aff = spec["affinity"]
    assert aff["enablePodAntiAffinity"] is True and aff["podAntiAffinityType"] == "required"
    assert aff["topologyKey"] == "kubernetes.io/hostname"
    (plugin,) = spec["plugins"]
    assert plugin["name"] == "barman-cloud.cloudnative-pg.io"
    store = plugin["parameters"]["barmanObjectName"]
    assert ("ObjectStore", store) in m
    (sb,) = of_kind("ScheduledBackup")
    assert sb["spec"]["cluster"]["name"] == "harbor-db"
    assert sb["spec"]["method"] == "plugin"


def test_obc_and_s3_mapping():
    m = manifests()
    obc = m[("ObjectBucketClaim", "harbor-registry-bucket")]
    assert obc["spec"]["storageClassName"] == "ceph-bucket"
    es = m[("ExternalSecret", "harbor-s3")]
    assert es["spec"]["secretStoreRef"]["kind"] == "SecretStore"
    tmpl = es["spec"]["target"]["template"]["data"]
    assert set(tmpl) == {"REGISTRY_STORAGE_S3_ACCESSKEY", "REGISTRY_STORAGE_S3_SECRETKEY"}
    store = m[("SecretStore", es["spec"]["secretStoreRef"]["name"])]
    assert store["spec"]["provider"]["kubernetes"]["remoteNamespace"] == "harbor"
    (role,) = of_kind("Role")
    assert role["rules"] == [{"apiGroups": [""], "resources": ["secrets"], "verbs": ["get"],
                              "resourceNames": ["harbor-registry-bucket"]}]
    assert of_kind("ServiceAccount") and of_kind("RoleBinding")


def test_external_secrets():
    m = manifests()
    paths = {"harbor-admin": "kv/harbor/admin", "harbor-secret-key": "kv/harbor/secret-key",
             "harbor-tls": "kv/harbor/tls", "harbor-bootstrap-robot": "kv/harbor/robot-ci",
             "harbor-core-secret": "kv/harbor/core", "harbor-core-token": "kv/harbor/core-token",
             "harbor-core-xsrf": "kv/harbor/core-xsrf",
             "harbor-jobservice-secret": "kv/harbor/jobservice",
             "harbor-registry-http": "kv/harbor/registry-http",
             "harbor-registry-credentials": "kv/harbor/registry-credentials"}
    for name, path in paths.items():
        spec = m[("ExternalSecret", name)]["spec"]
        assert spec["secretStoreRef"] == {"kind": "ClusterSecretStore", "name": "openbao"}
        assert path in json.dumps(spec), name
    tls = m[("ExternalSecret", "harbor-tls")]["spec"]["target"]["template"]
    assert tls["type"] == "kubernetes.io/tls"
    assert set(tls["data"]) == {"tls.crt", "tls.key", "ca.crt"}
    keys = {"harbor-core-secret": {"secret"}, "harbor-core-xsrf": {"CSRF_KEY"},
            "harbor-jobservice-secret": {"JOBSERVICE_SECRET"},
            "harbor-registry-http": {"REGISTRY_HTTP_SECRET"},
            "harbor-registry-credentials": {"REGISTRY_PASSWD", "REGISTRY_HTPASSWD"}}
    for name, want in keys.items():
        assert {d["secretKey"] for d in m[("ExternalSecret", name)]["spec"]["data"]} == want
    token = m[("ExternalSecret", "harbor-core-token")]["spec"]["target"]["template"]
    assert set(token["data"]) == {"tls.crt", "tls.key"}


# Secret/ConfigMap names the chart renders for release "harbor".
CHART_NAMES = {"harbor-core", "harbor-jobservice", "harbor-jobservice-env", "harbor-registry",
               "harbor-registry-htpasswd", "harbor-registryctl", "harbor-portal",
               "harbor-exporter", "harbor-exporter-env", "harbor-ingress", "harbor-trivy"}


def test_no_name_clash_with_chart():
    m = manifests()
    ours = {d["spec"]["target"]["name"] for d in of_kind("ExternalSecret")}
    ours |= {n for (k, n) in m if k == "ObjectBucketClaim"}  # Rook writes Secret + CM
    assert not ours & CHART_NAMES
    if _have_helm():
        theirs = {d["metadata"]["name"] for d in yaml.safe_load_all(_helm_template())
                  if d and d["kind"] in ("Secret", "ConfigMap")}
        assert not ours & theirs


def _rules(cnp, key):
    return cnp["spec"].get(key, [])


def test_network_policies():
    cnps = of_kind("CiliumNetworkPolicy")
    # Harbor app pods never leave the cluster; only harbor-db reaches the offsite store.
    app = [c for c in cnps if "harbor-db" not in json.dumps(c["spec"]["endpointSelector"])]
    text = json.dumps(app)
    for banned in ('"toCIDR"', '"toCIDRSet"', '"toFQDNs"', '"world"'):
        assert banned not in text, banned
    ingress = [r for c in cnps for r in _rules(c, "ingress")]
    assert {"matchLabels": {"k8s:io.kubernetes.pod.namespace": "traefik"}} in [
        e for r in ingress for e in r["fromEndpoints"]]
    egress = [r for c in cnps for r in _rules(c, "egress")]
    db = [r for r in egress
          if any(e.get("matchLabels", {}).get("cnpg.io/cluster") == "harbor-db"
                 for e in r.get("toEndpoints", []))]
    assert db and db[0]["toPorts"][0]["ports"][0]["port"] == "5432"
    assert any(e.get("matchLabels", {}).get("k8s:io.kubernetes.pod.namespace") == "rook-ceph"
               for r in egress for e in r.get("toEndpoints", []))


def _helm_template():
    return subprocess.run(
        ["helm", "template", "harbor", str(CHART), "-n", "harbor",
         "-f", str(ROOT / "values.yaml")],
        check=True, capture_output=True, text=True).stdout


def _have_helm():
    return shutil.which("helm") and CHART.is_file()


def test_pdbs_match_chart_labels():
    pdbs = {d["spec"]["selector"]["matchLabels"]["component"]: d for d in of_kind(
        "PodDisruptionBudget")}
    assert set(pdbs) == set(HA)
    if _have_helm():
        pods = {}
        for d in yaml.safe_load_all(_helm_template()):
            if d and d["kind"] == "Deployment":
                labels = d["spec"]["template"]["metadata"]["labels"]
                pods[labels.get("component")] = labels
    else:
        pods = {c: {"app": "harbor", "release": "harbor", "component": c} for c in HA}
    for c, pdb in pdbs.items():
        assert pdb["spec"]["maxUnavailable"] == 1
        sel = pdb["spec"]["selector"]["matchLabels"]
        assert sel.items() <= pods[c].items(), c


def test_homelab_unchanged():
    assert "harbor" not in (REPO / "deploy/k8s/kustomization.yaml").read_text()


@pytest.mark.skipif(not _have_helm(), reason="helm or vendored chart missing")
def test_helm_render():
    docs = [d for d in yaml.safe_load_all(_helm_template()) if d]
    deps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "Deployment"}
    assert not [n for n in deps if "trivy" in n]
    assert not [d for d in docs if d["kind"] == "StatefulSet" and "trivy" in d["metadata"]["name"]]
    for c in HA:
        assert deps[f"harbor-{c}"]["spec"]["replicas"] == 2, c
    for d in docs:
        pod = d.get("spec", {}).get("template", {}).get("spec", {})
        for ctr in pod.get("containers", []) + pod.get("initContainers", []):
            assert ctr["image"].startswith("harbor.example.internal/"), ctr["image"]


@pytest.mark.skipif(not _have_helm(), reason="helm or vendored chart missing")
def test_render_deterministic():
    # random chart secrets would rotate keys and roll every pod on each apply
    assert _helm_template() == _helm_template()


def _cnp_for_db(cnps):
    return [c for c in cnps
            if c["spec"]["endpointSelector"].get("matchLabels") == {"cnpg.io/cluster": "harbor-db"}]


def test_harbor_db_operator_and_backup_flows():
    db = _cnp_for_db(of_kind("CiliumNetworkPolicy"))
    ingress = [r for c in db for r in _rules(c, "ingress")]
    assert any({"matchLabels": {"k8s:io.kubernetes.pod.namespace": "cnpg-system"}}
               in r.get("fromEndpoints", []) and
               r["toPorts"][0]["ports"][0]["port"] == "8000" for r in ingress)
    egress = [r for c in db for r in _rules(c, "egress")]
    cidr = [r for r in egress if "toCIDRSet" in r]
    assert cidr and cidr[0]["toPorts"][0]["ports"][0]["port"] == "443"
    text = json.dumps(db)
    for banned in ('"toFQDNs"', '"world"', '"0.0.0.0/0"'):
        assert banned not in text, banned


def test_readme_has_no_stale_limits():
    readme = (ROOT / "README.md").read_text()
    assert "(`registry.credentials`)" not in readme
    assert "is not\n  in `networkpolicy.yaml`" not in readme
