"""RTO/RPO rules, evidence schema, overall pass, secret redaction (issue #15)."""

import json
from datetime import UTC, datetime, timedelta

from drtest import report

from .conftest import NS, RUN, SECRETS, UID, full_run_setup

T = datetime(2026, 11, 10, 0, 0, tzinfo=UTC)


def test_rto_exactly_8h_passes():
    assert report.rto(T, T + timedelta(hours=8)) == (8 * 3600, True)


def test_rto_8h_plus_1s_fails():
    assert report.rto(T, T + timedelta(hours=8, seconds=1)) == (8 * 3600 + 1, False)


def test_rto_missing_end_fails():
    assert report.rto(T, None) == (None, False)


def test_rpo_24h_boundary():
    assert report.rpo(T, T - timedelta(hours=24)) == (24 * 3600, True)
    assert report.rpo(T, T - timedelta(hours=24, seconds=1))[1] is False
    assert report.rpo(T, None) == (None, False)


def test_data_only_t0_is_harness_start():
    state = {"started": "2026-11-10T01:00:00Z"}
    steps = [{"id": "T0", "start": "2026-11-09T00:00:00Z"}]
    assert report.t0({"mode": "data-only"}, state, steps) == T + timedelta(hours=1)


def test_full_site_t0_is_mark():
    state = {"started": "2026-11-10T01:00:00Z"}
    steps = [{"id": "T0", "start": "2026-11-09T00:00:00Z", "end": None}]
    assert report.t0({"mode": "full-site"}, state, steps) == T - timedelta(days=1)
    assert report.t0({"mode": "full-site"}, state, []) is None


def full_run(h, health):
    full_run_setup(h, health)
    r = h.cli("run", "--confirm", RUN)
    return r, h.run_dir()


def test_report_schema_fields(h, health):
    r, d = full_run(h, health)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((d / "report.json").read_text())
    for k in ("schema_version", "run_id", "mode", "target", "operator", "witness", "git_sha",
              "tool_versions", "steps", "datasets", "rto_seconds", "pass", "controls",
              "log_sha256", "rto_clock_start"):
        assert k in rep, k
    assert rep["schema_version"] == "1.0"
    assert rep["controls"] == ["CP-4", "CP-9", "CP-10", "R03"]
    assert rep["target"] == {"cluster_uid": UID, "namespace": NS}
    assert rep["pass"] is True
    for s in rep["steps"]:
        assert set(s) >= {"id", "start", "end", "actor", "command", "result"}
    for ds in rep["datasets"]:
        assert set(ds) >= {"source", "backup_id", "recovered_point", "rpo_seconds", "checks"}
        for c in ds["checks"]:
            assert set(c) == {"name", "pass", "detail"}
    sources = [ds["source"] for ds in rep["datasets"]]
    assert sources[:2] == ["cnpg", "velero"] and "app" in sources
    kopia = next(ds for ds in rep["datasets"] if ds["source"].startswith("kopia"))
    assert kopia["backup_id"] == "s1"  # newest snapshot
    assert (d / "report.md").read_text().startswith("# DR restore test")
    assert len(rep["log_sha256"]) == 64


def test_overall_pass_false_if_any_check_fails(h, health):
    h.on(r"^pg_amcheck", code=2)
    r, d = full_run(h, health)
    assert r.returncode == 1
    assert json.loads((d / "report.json").read_text())["pass"] is False


def test_overall_pass_false_if_rpo_fails(h, health):
    h.cfg["incident_time"] = "2026-11-30T00:00:00Z"
    r, d = full_run(h, health)
    assert r.returncode == 1
    assert json.loads((d / "report.json").read_text())["pass"] is False


def test_report_subcommand_rebuilds(h, health):
    full_run(h, health)
    r = h.cli("report")
    assert r.returncode == 0, r.stderr


def test_secrets_never_written(h, health):
    # A tool that echoes a secret in its error output must not leak it anywhere.
    h.on(r"^pg_amcheck", out=f"auth failed for password {SECRETS['PGPASSWORD']}", code=1)
    r, d = full_run(h, health)
    plan = h.cli("plan")
    blobs = [r.stdout, r.stderr, plan.stdout, plan.stderr]
    blobs += [p.read_text() for p in d.iterdir() if p.is_file() and p.suffix != ".config"]
    assert any("auth failed" in b for b in blobs)
    for b in blobs:
        for v in SECRETS.values():
            assert v not in b
