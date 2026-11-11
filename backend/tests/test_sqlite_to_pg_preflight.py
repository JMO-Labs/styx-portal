"""Preflight scan (tests 9-16): read-only, lists data PostgreSQL would reject."""
import asyncio
import hashlib

import pytest
import sqlalchemy as sa

from app.tools import migrate_preflight as pf
from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source, raw_exec

PG = "postgresql+asyncpg://u:secretpw@localhost/db"
NOW = "2026-01-01 00:00:00.000000"


@pytest.fixture
def src(tmp_path):
    return asyncio.run(make_source(tmp_path / "s.db"))


def _user(path, uid="u1", **over):
    cols = {"id": uid, "username": f"n{uid}", "password_hash": "x", "role": "user",
            "is_active": 1, "must_change_pw": 0, "token_version": 0, "failed_count": 0, "matrix_serial": 0, "created_at": NOW}
    cols.update(over)
    raw_exec(path, f"INSERT INTO users ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
             tuple(cols.values()))


def _token(path, jti="j1", user_id="ghost", **over):
    cols = {"jti": jti, "user_id": user_id, "family_id": "", "expires_at": NOW,
            "revoked": 0, "session_only": 0, "created_at": NOW}
    cols.update(over)
    raw_exec(path, f"INSERT INTO refresh_tokens ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
             tuple(cols.values()))


def _kinds(res):
    return {(f.kind, f.table) for f in res.findings}


def test_clean_db_no_findings(src):
    _user(src)
    _token(src, user_id="u1")
    assert pf.scan(src).findings == []


def test_orphan_refresh_token_reported(src):
    _token(src)
    (f,) = pf.scan(src).findings
    assert (f.kind, f.table, f.pk) == ("orphan", "refresh_tokens", "j1")
    assert "users" in f.detail and "ghost" in f.detail


def test_null_in_not_null(tmp_path):
    # SQLite columns added by later migrations may lack NOT NULL; the model metadata is the truth.
    path = tmp_path / "n.db"
    raw_exec(path, "CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
    raw_exec(path, "INSERT INTO t (id, name) VALUES (1, NULL)")
    md = sa.MetaData()
    sa.Table("t", md, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String, nullable=False))
    (f,) = pf.scan(path, metadata=md).findings
    assert (f.kind, f.table, f.pk) == ("null", "t", "1")


def test_boolean_two(src):
    _user(src, is_active=2)
    assert ("boolean", "users") in _kinds(pf.scan(src))


def test_nul_byte_text(src):
    _user(src, username="a\x00b")
    assert ("nul", "users") in _kinds(pf.scan(src))


def test_bad_datetime(src):
    _user(src, created_at="not-a-date")
    assert ("datetime", "users") in _kinds(pf.scan(src))


def test_bad_json(src):
    raw_exec(src, "INSERT INTO system_settings (key, value, updated_at) VALUES ('k', '{oops', ?)", (NOW,))
    assert ("json", "system_settings") in _kinds(pf.scan(src))


def test_drop_orphans_skips_only_orphans_and_null_aborts(src):
    _token(src, "j1")
    _token(src, "j2")
    res = pf.scan(src, drop_orphans=True)
    assert res.skipped == {"refresh_tokens": {("j1",), ("j2",)}}
    assert res.blocking == []
    _user(src, is_active=2)
    assert [f.kind for f in pf.scan(src, drop_orphans=True).blocking] == ["boolean"]


def test_cascade_skips_children_of_skipped_rows(tmp_path):
    # chain root <- mid <- leaf; mid row is a direct orphan, leaf only dangles once mid is dropped
    path = tmp_path / "c.db"
    raw_exec(path, "CREATE TABLE root (id INTEGER PRIMARY KEY)")
    raw_exec(path, "CREATE TABLE mid (id INTEGER PRIMARY KEY, root_id INTEGER)")
    raw_exec(path, "CREATE TABLE leaf (id INTEGER PRIMARY KEY, mid_id INTEGER)")
    raw_exec(path, "INSERT INTO mid (id, root_id) VALUES (1, 99)")
    raw_exec(path, "INSERT INTO leaf (id, mid_id) VALUES (7, 1)")
    md = sa.MetaData()
    sa.Table("root", md, sa.Column("id", sa.Integer, primary_key=True))
    sa.Table("mid", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("root_id", sa.ForeignKey("root.id")))
    sa.Table("leaf", md, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("mid_id", sa.ForeignKey("mid.id")))
    plain = pf.scan(path, metadata=md)
    assert {(f.table, f.pk) for f in plain.findings} == {("mid", "1")}  # leaf fine until mid is dropped
    res = pf.scan(path, drop_orphans=True, metadata=md)
    assert (1,) in res.skipped["mid"] and (7,) in res.skipped["leaf"]
    assert ("leaf", "7") in {(f.table, f.pk) for f in res.findings}
    assert res.counts["leaf"] == 0


def test_scan_does_not_modify_source(src):
    _token(src)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    pf.scan(src)
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_orphan_exits_2_and_lists(src, capsys, monkeypatch):
    _token(src)
    monkeypatch.setattr(tool, "check_target_version", _noop)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    assert tool.main(["--source", str(src), "--target", PG]) == 2
    err = capsys.readouterr().err
    assert "refresh_tokens" in err and "j1" in err and "ghost" in err
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


def test_drop_orphans_exit_0_lists_skipped(src, capsys, monkeypatch):
    _token(src)
    monkeypatch.setattr(tool, "check_target_version", _noop)
    monkeypatch.setattr(tool, "check_target_empty", _noop)
    assert tool.main(["--source", str(src), "--target", PG, "--dry-run", "--drop-orphans"]) == 0
    assert "skipped refresh_tokens j1" in capsys.readouterr().out


def test_dry_run_prints_counts_and_hash_unchanged(src, capsys, monkeypatch):
    _user(src)
    monkeypatch.setattr(tool, "check_target_version", _noop)
    monkeypatch.setattr(tool, "check_target_empty", _noop)
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    assert tool.main(["--source", str(src), "--target", PG, "--dry-run"]) == 0
    assert "users: 1" in capsys.readouterr().out
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before


async def _noop(*_a, **_k):
    return None
