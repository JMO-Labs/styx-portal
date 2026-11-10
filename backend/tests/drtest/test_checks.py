"""Integrity checks: DB fingerprint, amcheck, Alembic, Velero, Kopia, health (issue #15)."""

import json
import re

from drtest import checks
from drtest.restorers import kopia, velero
from drtest.run import Runner, Sink

from .conftest import base_cfg, full_run_setup

CONN = {"host": "dst", "port": 5432, "user": "app", "dbname": "styx"}
FORBIDDEN = re.compile(r"\b(INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|TRUNCATE|GRANT)\b", re.I)


def runner():
    return Runner(Sink())


def test_rowcount_and_checksum_match_baseline(fake_env):
    fake_env.on(r"^psql .*FROM \"users\"", out="3|aaa")
    fake_env.apply()
    got = checks.fingerprint_tables(runner(), CONN, {"users": "id"})
    res = checks.table_checks(got, {"users": {"count": 3, "md5": "aaa"}})
    assert [c["pass"] for c in res] == [True]
    assert set(res[0]) == {"name", "pass", "detail"}


def test_checksum_mismatch_fails(fake_env):
    fake_env.on(r"^psql .*FROM \"users\"", out="3|zzz")
    fake_env.on(r"^psql .*FROM \"groups\"", out="1|bbb")
    fake_env.apply()
    got = checks.fingerprint_tables(runner(), CONN, {"users": "id", "groups": "id"})
    res = checks.table_checks(got, {"users": {"count": 3, "md5": "aaa"},
                                    "groups": {"count": 1, "md5": "bbb"}})
    bad = [c for c in res if not c["pass"]]
    assert len(bad) == 1 and "users" in bad[0]["name"]


def test_missing_baseline_table_fails():
    res = checks.table_checks({"users": {"count": 1, "md5": "a"}}, {})
    assert not res[0]["pass"]


def test_bad_table_identifier_refused():
    import pytest

    from drtest.guards import Refused
    with pytest.raises(Refused):
        checks.fingerprint_sql('users"; DROP TABLE x; --', "id")


def test_amcheck_failure_fails(fake_env):
    fake_env.on(r"^pg_amcheck", out="heap corruption", code=2)
    fake_env.apply()
    c = checks.amcheck(runner(), CONN)
    assert not c["pass"]
    argv = fake_env.calls()[-1]
    assert "--heapallindexed" in argv


def test_alembic_head_mismatch_fails(fake_env):
    fake_env.on(r"^psql .*alembic_version", out="head0")
    fake_env.apply()
    assert not checks.alembic(runner(), CONN, "head1")["pass"]
    assert checks.alembic(runner(), CONN, "head0")["pass"]


def test_velero_partially_failed_fails(fake_env):
    fake_env.on(r"^velero restore get", out='{"status":{"phase":"PartiallyFailed","errors":2}}')
    fake_env.apply()
    ds = velero.verify(base_cfg(fake_env.tmp), runner())
    assert not all(c["pass"] for c in ds["checks"])
    assert ds["recovered_point"] == "2026-11-09T02:00:00Z"


def test_velero_completed_with_errors_fails(fake_env):
    fake_env.on(r"^velero restore get", out='{"status":{"phase":"Completed","errors":1}}')
    fake_env.apply()
    ds = velero.verify(base_cfg(fake_env.tmp), runner())
    assert not all(c["pass"] for c in ds["checks"])


def test_kopia_verify_error_fails(fake_env):
    fake_env.on(r"^kopia .*snapshot verify", code=1)
    fake_env.apply()
    assert not kopia.verify_snapshot(runner(), ["kopia"], "s1")["pass"]


def test_sha256_sample_mismatch_fails(fake_env, tmp_path):
    d = tmp_path / "r"
    d.mkdir()
    (d / "a.txt").write_bytes(b"hello\n")
    fake_env.on(r"^kopia .*show k1/a.txt", out=b"HELLO\n")
    fake_env.apply()
    c = checks.sha256_sample(runner(), ["kopia"], "k1", d, 5, "t1")
    assert not c["pass"] and "a.txt" in c["detail"]
    fake_env.on(r"^kopia .*show k1/a.txt", out=b"hello\n")
    fake_env.apply()
    assert checks.sha256_sample(runner(), ["kopia"], "k1", d, 5, "t1")["pass"]


def test_sha256_sample_empty_restore_fails(fake_env, tmp_path):
    (tmp_path / "r").mkdir()
    assert not checks.sha256_sample(runner(), ["kopia"], "k1", tmp_path / "r", 5, "t1")["pass"]


def test_health_non_200_fails(health):
    health.code = 503
    c, t = checks.health(health.url, 1, 0)
    assert not c["pass"] and t is None
    health.code = 200
    c, t = checks.health(health.url, 1, 0)
    assert c["pass"] and t is not None


def test_fingerprint_is_read_only(h, health):
    full_run_setup(h, health)
    out = h.tmp / "fp.json"
    r = h.cli("fingerprint", "--out", str(out))
    assert r.returncode == 0, r.stderr
    psql = [c for c in h.calls() if c[0] == "psql"]
    assert len(psql) == 2
    for c in psql:
        sql = c[c.index("-c") + 1]
        assert sql.lstrip().upper().startswith("SELECT")
        assert not FORBIDDEN.search(sql)
        assert c[c.index("-h") + 1] == "src"
    assert h.writes() == []
    fp = json.loads(out.read_text())
    assert fp["tables"]["users"] == {"count": 3, "md5": "aaa"}
