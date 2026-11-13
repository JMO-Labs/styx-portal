"""Backup validators reject known-bad input (issues #37, #38; alerts and CNPG overlay split)."""

import copy

import pytest

from tests.backup_checks import (
    BACKUP,
    alerts,
    check_backup_dir,
    check_cronjob,
    check_schedules,
    check_snapshot_name,
    check_stale_alerts,
    load_docs,
    load_rule,
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


def test_stale_without_absent_is_error():
    r = load_rule()
    a = alerts(r)["CnpgBackupStale"]
    a["expr"] = "time() - barman_cloud_cloudnative_pg_io_last_available_backup_timestamp > 93600"
    with pytest.raises(ValueError, match="absent"):
        check_stale_alerts(r)


def test_stale_without_26h_is_error():
    r = load_rule()
    alerts(r)["VeleroBackupStale"]["expr"] = "absent(x) or time() - x > 1"
    with pytest.raises(ValueError, match="93600"):
        check_stale_alerts(r)


def test_cnpg_object_in_backup_dir_is_error(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "apiVersion: barmancloud.cnpg.io/v1\nkind: ObjectStore\nmetadata: {name: a}\n"
    )
    with pytest.raises(ValueError, match="ObjectStore"):
        check_backup_dir(tmp_path)


@pytest.mark.parametrize("kind", ["ScheduledBackup", "Cluster"])
def test_other_cnpg_kinds_are_errors(tmp_path, kind):
    (tmp_path / "x.yaml").write_text(f"apiVersion: postgresql.cnpg.io/v1\nkind: {kind}\nmetadata: {{name: a}}\n")
    with pytest.raises(ValueError, match=kind):
        check_backup_dir(tmp_path)


def test_cnpg_object_in_subdir_is_error(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.yaml").write_text(
        "apiVersion: barmancloud.cnpg.io/v1\nkind: ObjectStore\nmetadata: {name: a}\n"
    )
    with pytest.raises(ValueError, match="ObjectStore"):
        check_backup_dir(tmp_path)


def test_plain_secret_stringdata_is_error(tmp_path):
    (tmp_path / "s.yaml").write_text(
        "apiVersion: v1\nkind: Secret\nmetadata: {name: s}\nstringData: {k: v}\n"
    )
    with pytest.raises(ValueError, match="stringData"):
        check_backup_dir(tmp_path)


def test_real_backup_dir_is_clean():
    check_backup_dir()
