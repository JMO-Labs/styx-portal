import pytest

from tests.backup_checks import alerts, check_backup_dir, check_stale_alerts, load_rule


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


def test_plain_secret_stringdata_is_error(tmp_path):
    (tmp_path / "s.yaml").write_text(
        "apiVersion: v1\nkind: Secret\nmetadata: {name: s}\nstringData: {k: v}\n"
    )
    with pytest.raises(ValueError, match="stringData"):
        check_backup_dir(tmp_path)


def test_real_backup_dir_is_clean():
    check_backup_dir()
