"""No path may yield PASS evidence for a run that failed or verified nothing (#15 pass 4)."""

import json

import pytest

from drtest import report

from .conftest import RUN, full_run_setup


def rep(h):
    return json.loads((h.run_dir() / "report.json").read_text())


def test_rerun_of_finished_run_id_refused(h, health):
    full_run_setup(h, health)
    assert h.cli("run", "--confirm", RUN).returncode == 0
    first = (h.run_dir() / "report.json").read_text()
    h.on(r"^kubectl get namespace styx-drtest-t1",
         out=json.dumps({"metadata": {"labels": {"styx.io/dr-scratch": "true",
                                                 "styx.io/dr-run": RUN}}}))
    h.on(r"^velero restore create", code=1)
    h.log.unlink()
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 2, r.stdout + r.stderr
    assert "REFUSED" in r.stderr
    assert h.writes() == []
    assert (h.run_dir() / "report.json").read_text() == first


def test_aborted_state_never_passes(h, health):
    # A report rebuilt from an aborted run's dir stays FAIL, whatever else is in it.
    full_run_setup(h, health)
    h.on(r"^kopia .*snapshot restore", code=1)
    assert h.cli("run", "--confirm", RUN).returncode == 3
    assert rep(h)["pass"] is False
    assert h.cli("report").returncode == 1
    assert rep(h)["pass"] is False


EMPTY = {
    "kopia-no-sources": lambda c: (c.pop("cnpg"), c.pop("velero"),
                                   c["kopia"].update(sources=[])),
    "cnpg-no-tables": lambda c: (c.pop("velero"), c.pop("kopia"),
                                 c["cnpg"].update(tables={})),
    "velero-no-namespaces": lambda c: (c.pop("cnpg"), c.pop("kopia"),
                                       c["velero"].update(include_namespaces=[])),
}


@pytest.mark.parametrize("name", EMPTY)
def test_empty_data_source_refused(h, health, name):
    full_run_setup(h, health)
    EMPTY[name](h.cfg)
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 2, r.stdout + r.stderr
    assert h.writes() == []


def test_empty_fingerprint_baseline_fails(h, health):
    full_run_setup(h, health)
    (h.tmp / "fingerprint.json").write_text(json.dumps({"tables": {}}))
    r = h.cli("run", "--confirm", RUN)
    assert r.returncode == 1
    assert rep(h)["pass"] is False


def test_zero_file_sha256_sample_fails(h, health):
    full_run_setup(h, health)
    h.cfg["kopia"]["sample"] = 0
    assert h.cli("run", "--confirm", RUN).returncode == 1
    assert rep(h)["pass"] is False


def test_negative_rto_and_rpo_fail():
    from datetime import UTC, datetime, timedelta
    t = datetime(2026, 11, 10, tzinfo=UTC)
    assert report.rto(t, t - timedelta(seconds=1)) == (-1, False)
    assert report.rpo(t, t + timedelta(seconds=1)) == (-1, False)


def test_rpo_incident_before_recovered_point_fails(h, health):
    full_run_setup(h, health)
    h.cfg["incident_time"] = "2026-11-01T00:00:00Z"
    assert h.cli("run", "--confirm", RUN).returncode == 1
    assert rep(h)["pass"] is False


def test_dataset_without_checks_fails(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "started": "2026-11-10T00:00:00Z", "t_end": "2026-11-10T01:00:00Z",
        "datasets": [{"source": "kopia:x", "backup_id": "s1",
                      "recovered_point": "2026-11-09T23:00:00Z", "checks": []},
                     {"source": "app", "backup_id": None, "recovered_point": None,
                      "checks": [{"name": "app:health", "pass": True, "detail": ""}]}]}))
    cfg = {"run_id": RUN, "mode": "data-only", "namespace": "styx-drtest-t1"}
    assert report.build(cfg, tmp_path)["pass"] is False


def test_only_app_dataset_fails(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({
        "started": "2026-11-10T00:00:00Z", "t_end": "2026-11-10T01:00:00Z",
        "datasets": [{"source": "app", "backup_id": None, "recovered_point": None,
                      "checks": [{"name": "app:health", "pass": True, "detail": ""}]}]}))
    cfg = {"run_id": RUN, "mode": "data-only", "namespace": "styx-drtest-t1"}
    assert report.build(cfg, tmp_path)["pass"] is False


def test_keyboard_interrupt_after_writes_aborts_with_report(fake_env, health, monkeypatch,
                                                            capsys):
    from drtest import checks, cli

    def interrupt(*a, **k):
        raise KeyboardInterrupt

    full_run_setup(fake_env, health)
    fake_env.apply()
    monkeypatch.setattr(checks, "health", interrupt)
    cfg = fake_env.tmp / "drtest.json"
    cfg.write_text(json.dumps(fake_env.cfg))
    assert cli.main(["-c", str(cfg), "run", "--confirm", RUN]) == 3
    assert "ABORTED" in capsys.readouterr().err
    assert rep(fake_env)["pass"] is False
