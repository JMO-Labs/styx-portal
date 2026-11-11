"""Static checks for deploy/enterprise/backup Velero install."""

import copy

import yaml

from tests.backup_checks import BACKUP, check_bsl, check_externalsecrets, check_images, load_docs


def values() -> dict:
    return yaml.safe_load((BACKUP / "velero-values.yaml").read_text())


def test_kustomization_lists_all_files():
    k = yaml.safe_load((BACKUP / "kustomization.yaml").read_text())
    on_disk = {p.name for p in BACKUP.glob("*.yaml")} - {"velero-values.yaml", "kustomization.yaml"}
    assert set(k["resources"]) == on_disk
    assert list(BACKUP.glob("charts/velero-*.tgz"))
    ns = {d["metadata"]["name"] for d in load_docs(BACKUP / "namespace.yaml")}
    assert ns == {"velero", "styx-backup"}


def test_velero_images_pinned_to_harbor():
    assert check_images(values()) == []
    bad = copy.deepcopy(values())
    bad["image"]["digest"] = "sha256:abc"
    bad["kubectl"]["image"]["repository"] = "registry.k8s.io/kubectl"
    assert len(check_images(bad)) >= 2


def test_bsl_offsite_and_no_fs_backup():
    assert check_bsl(values()) == []
    bad = copy.deepcopy(values())
    bad["deployNodeAgent"] = True
    bad["configuration"]["defaultVolumesToFsBackup"] = True
    bad["configuration"]["backupStorageLocation"].append({"name": "x"})
    assert len(check_bsl(bad)) >= 3


def test_repo_password_from_eso():
    docs = load_docs(BACKUP / "velero-externalsecrets.yaml")
    assert check_externalsecrets(docs) == []
    assert check_externalsecrets([{"kind": "Secret", "metadata": {"name": "x"}}])
