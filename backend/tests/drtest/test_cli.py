"""CLI: confirm gate, read-only plan, manual step marks (issue #15)."""

import re

from drtest import report

from .conftest import RUN, SECRETS

ISO_UTC = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


def test_run_requires_confirm(h):
    r = h.cli("run")
    assert r.returncode != 0
    assert h.calls() == []
    assert not (h.tmp / "evidence").exists()


def test_run_confirm_mismatch(h):
    r = h.cli("run", "--confirm", "t2")
    assert r.returncode != 0
    assert h.calls() == []
    assert not (h.tmp / "evidence").exists()


def test_plan_executes_no_writes(h):
    r = h.cli("plan")
    assert r.returncode == 0, r.stderr
    assert h.only_reads()
    assert h.writes() == []
    assert not (h.tmp / "evidence").exists()
    out = r.stdout
    assert "kubectl create -f -" in out and '"styx.io/dr-run": "t1"' in out
    assert '"kind": "Cluster"' in out and '"recovery"' in out
    assert "velero restore create" in out and "--include-cluster-resources=false" in out
    assert "repository connect s3" in out and "--readonly" in out
    assert "snapshot restore" in out
    for v in SECRETS.values():
        assert v not in out


def test_mark_records_step(h):
    assert h.cli("mark", "T0", "start").returncode == 0
    assert h.cli("mark", "T0", "end", "--actor", "alice").returncode == 0
    steps = report.load_steps(h.run_dir())
    assert len(steps) == 1
    s = steps[0]
    assert s["id"] == "T0" and s["actor"] == "alice"
    assert ISO_UTC.match(s["start"]) and ISO_UTC.match(s["end"])
    assert h.run_dir().name.endswith(f"-{RUN}")


def test_mark_rejects_bad_step_id(h):
    assert h.cli("mark", "../x", "start").returncode == 2


def test_config_with_secret_key_is_refused(h):
    h.cfg["kopia"]["s3"]["secret_access_key"] = "nope-SENTINEL"
    r = h.cli("plan")
    assert r.returncode == 2
    assert "nope-SENTINEL" not in r.stdout + r.stderr


def test_example_config_loads():
    from drtest import cli, run

    from .conftest import HARNESS
    cfg = cli.load_config(HARNESS / "drtest.example.json")
    for ns in run.scratch_namespaces(cfg):
        run.guards.namespace_name(ns)
