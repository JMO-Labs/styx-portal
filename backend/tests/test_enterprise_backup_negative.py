import pytest

from tests.backup_checks import alerts, check_stale_alerts, load_rule


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
