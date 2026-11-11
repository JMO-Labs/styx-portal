"""Backup validators reject known-bad input (issues #37, #38)."""

import copy

import pytest

from tests.backup_checks import (
    BACKUP,
    check_cronjob,
    check_schedules,
    check_snapshot_name,
    load_docs,
)


@pytest.mark.parametrize("name", ["scheduled-2026-11-10-03_00_00_UTC", "nightly-20261110",
                                  "manual-x", "nightly-2026-11-10-extra"])
def test_bad_snapshot_names_rejected(name):
    assert check_snapshot_name(name)


def test_good_snapshot_name_accepted():
    assert check_snapshot_name("nightly-2026-11-10") == []


def test_cronjob_with_ceph_admin_rejected():
    (cj,) = load_docs(BACKUP / "home-snapshots-cronjob.yaml")
    bad = copy.deepcopy(cj)
    vol = bad["spec"]["jobTemplate"]["spec"]["template"]["spec"]["volumes"][1]
    vol["secret"]["secretName"] = "rook-ceph-admin-keyring"
    assert any("admin" in e for e in check_cronjob(bad))


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
