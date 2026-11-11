import shutil
import subprocess

import pytest
import yaml

from backup_checks import RULE_FILE, alerts, check_stale_alerts, load_rule

NAMES = {
    "CnpgBackupStale", "CnpgBackupFailed", "CnpgWalArchivingFailing",
    "VeleroBackupStale", "VeleroBackupFailed", "VeleroBslUnavailable",
    "HomeSnapshotsStale", "HomeSnapshotsFailed",
}
STALE_METRICS = {
    "CnpgBackupStale": "barman_cloud_cloudnative_pg_io_last_available_backup_timestamp",
    "VeleroBackupStale": 'velero_backup_last_successful_timestamp{schedule="daily"}',
    "HomeSnapshotsStale": 'kube_cronjob_status_last_successful_time{cronjob="styx-home-snapshots"}',
}


def test_rule_metadata():
    r = load_rule()
    assert r["kind"] == "PrometheusRule"
    assert r["metadata"]["name"] == "styx-backup"
    assert r["metadata"]["labels"]["release"] == "kube-prometheus-stack"
    assert set(alerts(r)) == NAMES
    kust = yaml.safe_load((RULE_FILE.parent / "kustomization.yaml").read_text())
    assert "prometheusrule.yaml" in kust["resources"]


def test_stale_alerts_use_26h_and_absent():
    a = alerts(load_rule())
    check_stale_alerts(load_rule())
    for name, metric in STALE_METRICS.items():
        assert metric in a[name]["expr"], name
        assert "93600" in a[name]["expr"] and "absent(" in a[name]["expr"]


def test_failure_exprs():
    a = alerts(load_rule())
    assert "last_failed_backup_timestamp" in a["CnpgBackupFailed"]["expr"]
    assert ">" in a["CnpgBackupFailed"]["expr"]
    w = a["CnpgWalArchivingFailing"]["expr"]
    assert "cnpg_pg_stat_archiver_seconds_since_last_archival" in w and "> 900" in w
    assert "increase(cnpg_pg_stat_archiver_failed_count" in w
    v = a["VeleroBackupFailed"]["expr"]
    assert "increase(velero_backup_failure_total" in v
    assert "increase(velero_backup_partial_failure_total" in v
    assert "velero_backup_location_status_gauge" in a["VeleroBslUnavailable"]["expr"]
    assert "== 0" in a["VeleroBslUnavailable"]["expr"]
    assert 'kube_job_failed{job_name=~"styx-home-snapshots.*"' in a["HomeSnapshotsFailed"]["expr"]


def test_every_alert_has_severity_and_summary():
    for name, r in alerts(load_rule()).items():
        assert r["labels"].get("severity"), name
        assert r["annotations"].get("summary"), name


@pytest.mark.skipif(shutil.which("promtool") is None, reason="promtool absent")
def test_promtool(tmp_path):
    spec = tmp_path / "rules.yaml"
    spec.write_text(yaml.safe_dump({"groups": load_rule()["spec"]["groups"]}))
    subprocess.run(["promtool", "check", "rules", str(spec)], check=True)
