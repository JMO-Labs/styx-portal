"""The Velero schedule validator rejects known-bad schedules (issue #37)."""

import copy

from tests.backup_checks import BACKUP, check_schedules, load_docs


def good() -> list[dict]:
    return load_docs(BACKUP / "velero-schedules.yaml")


def test_fs_backup_rejected():
    bad = copy.deepcopy(good())
    bad[0]["spec"]["template"]["defaultVolumesToFsBackup"] = True
    assert any("defaultVolumesToFsBackup" in e for e in check_schedules(bad))


def test_missing_cnpg_exclusion_rejected():
    bad = copy.deepcopy(good())
    bad[1]["spec"]["template"]["excludedResources"] = ["events"]
    assert any("clusters.postgresql.cnpg.io" in e for e in check_schedules(bad))


def test_missing_namespace_exclusion_rejected():
    bad = copy.deepcopy(good())
    bad[0]["spec"]["template"]["excludedNamespaces"].remove("openbao")
    assert any("openbao" in e for e in check_schedules(bad))
