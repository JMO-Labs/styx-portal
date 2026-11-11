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


_Loader.add_constructor("tag:yaml.org,2002:value", lambda l, n: n.value)


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
