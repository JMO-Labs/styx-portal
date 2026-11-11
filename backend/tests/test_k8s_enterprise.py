import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
HOMELAB = DEPLOY / "k8s"
ENT = DEPLOY / "enterprise"

HOMELAB_ONLY = {
    ("CronJob", "styx-db-backup"),
    ("PersistentVolumeClaim", "styx-data"),
    ("PersistentVolumeClaim", "styx-backups"),
    ("StorageClass", "longhorn-styx"),
    ("Role", "styx-cloudflared-pods"),
    ("RoleBinding", "styx-cloudflared-pods"),
}


def _kustomization():
    return yaml.safe_load((ENT / "kustomization.yaml").read_text())


def _index():
    """Every YAML doc in deploy/enterprise/*.yaml (not kustomization) by (kind, name)."""
    out = {}
    for f in sorted(ENT.glob("*.yaml")):
        if f.name == "kustomization.yaml":
            continue
        for d in yaml.safe_load_all(f.read_text()):
            if d:
                out[(d["kind"], d["metadata"]["name"])] = d
    return out


def test_kustomization_bases_on_homelab():
    res = _kustomization()["resources"]
    assert "../k8s" in res
    for r in res:
        assert (ENT / r).exists(), r


def test_homelab_unchanged():
    (be,) = [d for d in yaml.safe_load_all((HOMELAB / "backend.yaml").read_text())
             if d["kind"] == "Deployment" and d["metadata"]["name"] == "backend"]
    assert be["spec"]["replicas"] == 1
    assert be["spec"]["strategy"]["type"] == "Recreate"
    listed = yaml.safe_load((HOMELAB / "kustomization.yaml").read_text())["resources"]
    assert "backup-cronjob.yaml" in listed and "pvc.yaml" in listed


def test_removes_homelab_only_resources():
    idx = _index()
    for key in HOMELAB_ONLY:
        assert key in idx, key
        assert idx[key]["$patch"] == "delete"


def test_no_secrets_committed():
    for f in ENT.glob("*.yaml"):
        for d in yaml.safe_load_all(f.read_text()):
            if d and d.get("kind") == "Secret":
                assert not d.get("data") and not d.get("stringData"), f.name


class _Loader(yaml.SafeLoader):
    """Kustomize emits bare `=` (matchType), a YAML 1.1 'value' tag in PyYAML."""


_Loader.add_constructor("tag:yaml.org,2002:value", lambda _loader, node: node.value)


def _build(path):
    tool = ["kustomize", "build"] if shutil.which("kustomize") else ["kubectl", "kustomize"]
    out = subprocess.run([*tool, str(path)], capture_output=True, text=True, check=True)
    return [d for d in yaml.load_all(out.stdout, Loader=_Loader) if d]


@pytest.mark.skipif(not (shutil.which("kustomize") or shutil.which("kubectl")),
                    reason="kustomize/kubectl not installed")
def test_kustomize_build():
    kinds = {(d["kind"], d["metadata"]["name"]) for d in _build(ENT)}
    assert not kinds & HOMELAB_ONLY
    assert not {k for k, _ in kinds} & {"CronJob", "PersistentVolumeClaim"}
    be = [d for d in _build(ENT) if d["kind"] == "Deployment" and d["metadata"]["name"] == "backend"]
    assert be[0]["spec"]["replicas"] == 3
    assert ("CronJob", "styx-db-backup") in {(d["kind"], d["metadata"]["name"])
                                             for d in _build(HOMELAB)}


def _walk(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield k
            yield from _walk(v)
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v)


def test_cluster_spec():
    c = _index()[("Cluster", "styx-db")]
    assert c["metadata"]["namespace"] == "styx"
    s = c["spec"]
    assert s["instances"] == 3
    assert s["imageName"].split(":")[1].split(".")[0].split("-")[0] == "17"
    assert s["enableSuperuserAccess"] is False
    aff = s["affinity"]
    assert aff["enablePodAntiAffinity"] is True
    assert aff["podAntiAffinityType"] == "required"
    assert aff["topologyKey"] == "kubernetes.io/hostname"
    init = s["bootstrap"]["initdb"]
    assert (init["database"], init["owner"], init["secret"]["name"]) == ("styx", "styx", "styx-db-app")
    assert s["postgresql"]["synchronous"] == {"method": "any", "number": 1, "dataDurability": "preferred"}
    assert "rook" in s["storage"]["storageClass"]
    assert s["plugins"] == [{"name": "barman-cloud.cloudnative-pg.io", "isWALArchiver": True,
                             "parameters": {"barmanObjectName": "styx-db-offsite"}}]
    assert s["backup"]["volumeSnapshot"]["className"]


def test_no_in_tree_barman():
    for f in ENT.glob("*.yaml"):
        for d in yaml.safe_load_all(f.read_text()):
            assert "barmanObjectStore" not in set(_walk(d)), f.name


def test_objectstore_retention_and_ssec():
    o = _index()[("ObjectStore", "styx-db-offsite")]
    assert o["apiVersion"] == "barmancloud.cnpg.io/v1"
    c = o["spec"]["configuration"]
    assert o["spec"]["retentionPolicy"] == "30d"
    assert c["destinationPath"]
    cr = c["s3Credentials"]
    for k in ("accessKeyId", "secretAccessKey", "sseCustomerKey"):
        assert cr[k]["name"] == "styx-db-bucket"
    assert c["wal"]["compression"] and c["data"]["compression"]


def test_two_scheduled_backups():
    sb = [d for (k, _), d in _index().items() if k == "ScheduledBackup"]
    assert {d["spec"]["method"] for d in sb} == {"plugin", "volumeSnapshot"}
    assert len(sb) == 2
    for d in sb:
        assert d["spec"]["cluster"]["name"] == "styx-db"
        assert d["spec"]["schedule"]
    plug = [d for d in sb if d["spec"]["method"] == "plugin"][0]
    assert plug["spec"]["pluginConfiguration"]["name"] == "barman-cloud.cloudnative-pg.io"
