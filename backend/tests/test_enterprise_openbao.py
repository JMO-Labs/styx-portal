"""Static checks for deploy/enterprise/openbao (issue #4, ADR-0042, ADR-0061)."""

import re

from tests.openbao_checks import (
    ESO, OPENBAO, ROOT, ceph_storage_refs, check_ha, check_images, check_raft_hcl,
    check_scheduling, check_security_context, check_storage, check_values, check_volumes,
    leaks, load_docs, load_yaml,
)

FILES = [
    "README.md", "values.yaml", "kustomization.yaml", "namespace.yaml", "storageclass.yaml",
    "local-pvs.yaml", "networkpolicy.yaml", "snapshot-cronjob.yaml", "snapshot-params.yaml",
    "snapshot-externalsecret.yaml", "snapshot-sa.yaml", "gen-bootstrap-tls.sh",
    "bao_configure.py", "auth-roles.json", "extra-mounts.json", "policies/eso-read.hcl",
    "policies/raft-snapshot.hcl", "ansible/seal-key.yml", "ansible/inventory.example.yml",
]
ESO_FILES = ["values.yaml", "kustomization.yaml", "namespace.yaml", "clustersecretstore.yaml"]
DOCS = ROOT / "docs/enterprise"


def values() -> dict:
    return load_yaml(OPENBAO / "values.yaml")


def docs(name: str) -> list[dict]:
    return load_docs(OPENBAO / name)


def test_files_exist():
    for f in FILES:
        assert (OPENBAO / f).is_file(), f
    for f in ESO_FILES:
        assert (ESO / f).is_file(), f
    assert (DOCS / "runbooks/openbao.md").is_file()


def test_kustomization_lists_all_files():
    for tree in (OPENBAO, ESO):
        listed = load_yaml(tree / "kustomization.yaml")["resources"]
        on_disk = {p.name for p in tree.glob("*.yaml")} - {"values.yaml", "kustomization.yaml"}
        assert set(listed) == on_disk, tree
        for f in listed:
            assert (tree / f).is_file(), f


def test_ha_raft_three_replicas():
    assert check_ha(values()) == []


def test_images_pinned_by_digest():
    assert check_images(values()) == []
    for f in ("snapshot-cronjob.yaml",):
        for doc in docs(f):
            assert check_images(doc) == [], f


def test_control_plane_pinning():
    assert check_scheduling(values()) == []


def test_raft_not_on_ceph():
    # Regression for the ADR-0061 deadlock: OSDs need OpenBao, so OpenBao must not need Ceph.
    assert check_storage(values()) == []
    (sc,) = docs("storageclass.yaml")
    assert sc["metadata"]["name"] == "openbao-local"
    assert sc["provisioner"] == "kubernetes.io/no-provisioner"
    assert sc["volumeBindingMode"] == "WaitForFirstConsumer"
    for tree in (OPENBAO, ESO):
        for path in tree.rglob("*.yaml"):
            for doc in load_docs(path):
                assert ceph_storage_refs(doc) == [], path


def test_local_pvs_one_per_control_plane():
    pvs = docs("local-pvs.yaml")
    assert len(pvs) == 3 and all(p["kind"] == "PersistentVolume" for p in pvs)
    hosts = set()
    for pv in pvs:
        spec = pv["spec"]
        assert spec["local"]["path"] == "/var/lib/openbao/raft"
        assert spec["storageClassName"] == "openbao-local"
        (term,) = spec["nodeAffinity"]["required"]["nodeSelectorTerms"]
        (expr,) = term["matchExpressions"]
        assert expr["key"] == "kubernetes.io/hostname" and expr["operator"] == "In"
        hosts.update(expr["values"])
    assert hosts == {"rke2-server-01", "rke2-server-02", "rke2-server-03"}


def test_static_seal_stanza():
    hcl = values()["server"]["ha"]["raft"]["config"]
    assert check_raft_hcl(hcl) == []
    # previous_* present but commented out, pointing at the rotation runbook.
    prev = [ln for ln in hcl.splitlines() if "previous_key" in ln]
    assert len(prev) == 2 and all(ln.lstrip().startswith("#") for ln in prev)
    assert "runbooks/openbao.md" in hcl


def test_audit_declared_to_stdout():
    # Declarative audit device (OpenBao 2.7 refuses API-created ones): path stdout/, file to stdout.
    hcl = values()["server"]["ha"]["raft"]["config"]
    assert re.search(r'^audit "file" "stdout" \{.*?file_path = "stdout".*?^\}', hcl, re.M | re.S)
    assert "unsafe_allow_api_audit_creation" not in hcl


def test_tls_enabled():
    v = values()
    hcl = v["server"]["ha"]["raft"]["config"]
    assert re.search(r'tls_key_file\s*=\s*"/openbao/tls/tls.key"', hcl)
    assert v["global"]["tlsDisable"] is False
    mounts = {m["name"]: m for m in v["server"]["volumeMounts"]}
    vols = {x["name"]: x for x in v["server"]["volumes"]}
    assert vols["tls"]["secret"]["secretName"] == "openbao-tls"
    assert mounts["tls"]["mountPath"] == "/openbao/tls" and mounts["tls"]["readOnly"] is True


def test_seal_hostpath_readonly_and_only_hostpath():
    assert check_volumes(values()) == []


def test_container_security_context():
    sc = values()["server"]["statefulSet"]["securityContext"]
    assert check_security_context(sc["pod"], sc["container"]) == []


def test_whole_values_pass():
    assert check_values(values()) == []


def test_namespace_psa_exception_documented():
    (ns,) = docs("namespace.yaml")
    labels = ns["metadata"]["labels"]
    assert ns["metadata"]["name"] == "openbao"
    assert labels["pod-security.kubernetes.io/enforce"] == "privileged"
    assert labels["pod-security.kubernetes.io/warn"] == "restricted"
    assert labels["pod-security.kubernetes.io/audit"] == "restricted"
    assert labels["styx.io/openbao-secrets"] == "true"
    raw = (OPENBAO / "namespace.yaml").read_text()
    assert "hostPath" in raw and "CM-6" in raw and "CM-7" in raw
    cm = (DOCS / "control-matrix.md").read_text()
    row = re.search(r"^\| CM-6 \|.*$", cm, re.M).group(0)
    assert "openbao" in row and "Pod Security Admission" in row


def _rules(policy: dict, direction: str) -> list[dict]:
    return policy["spec"].get(direction, [])


def test_networkpolicy_ingress_sources():
    pols = {d["metadata"]["name"]: d for d in docs("networkpolicy.yaml")}
    assert all(d["kind"] == "CiliumNetworkPolicy" for d in pols.values())
    assert all(d["metadata"]["namespace"] == "openbao" for d in pols.values())
    server = pols["openbao-server"]
    sources, peer_8201 = set(), False
    for rule in _rules(server, "ingress"):
        ports = {p["port"] for tp in rule["toPorts"] for p in tp["ports"]}
        for ep in rule.get("fromEndpoints", []):
            labels = ep["matchLabels"]
            if "8200" in ports:
                sources.add(labels["k8s:io.kubernetes.pod.namespace"])
            if "8201" in ports:
                assert labels.get("app.kubernetes.io/name") == "openbao", labels
                peer_8201 = True
        assert ports <= {"8200", "8201"}
    assert sources == {"external-secrets", "rook-ceph", "openbao"}
    assert peer_8201
    egress = _rules(server, "egress")
    assert {"kube-apiserver"} == {e for r in egress for e in r.get("toEntities", [])}
    assert not any("world" in r.get("toEntities", []) for r in egress)
    snap = pols["openbao-raft-snapshot"]
    world = [r for r in _rules(snap, "egress") if "world" in r.get("toEntities", [])]
    assert world and {p["port"] for r in world for tp in r["toPorts"] for p in tp["ports"]} == {"443"}


def _files(tree) -> list:
    # Every file in the tree (a superset of `git ls-files`), so the check needs no git.
    return [p for p in tree.rglob("*") if p.is_file()]


def test_no_secret_material_committed():
    files = _files(OPENBAO) + _files(ESO)
    for path in files:
        if path.suffix in (".tgz",):
            continue
        assert leaks(path.read_text()) == [], path
    bad = (ROOT / "backend/tests/fixtures/openbao_bad/leaky.yaml").read_text()
    assert "kind: Secret with data/stringData" in leaks(bad)
    assert leaks("current_key: " + "ab" * 32)
    assert leaks("-----BEGIN EC PRIVATE KEY-----")


def test_readme_pins_versions():
    text = (OPENBAO / "README.md").read_text()
    for item in ("openbao-0.30.7", "v2.7.2", "external-secrets 2.14.0", "v2.14.0"):
        assert item in text, item


def test_helm_test_pod_never_rendered():
    # The chart's test hook pod copies server.volumes (the seal hostPath) with no CP pinning.
    files = [ROOT / ".gitlab-ci.yml", OPENBAO / "README.md", OPENBAO / "values.yaml",
             OPENBAO / "kustomization.yaml"]
    renders = [ln for f in files for ln in f.read_text().splitlines()
               if "helm template openbao" in ln]
    assert renders
    assert all("--skip-tests" in ln for ln in renders), renders
    ci = (ROOT / ".gitlab-ci.yml").read_text()
    assert 'grep -c "path: /etc/openbao/seal"' in ci  # CI asserts one seal hostPath rendered
    assert "never run `helm test`" in (ROOT / "docs/enterprise/runbooks/openbao.md").read_text()
