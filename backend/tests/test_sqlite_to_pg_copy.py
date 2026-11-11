"""pg_only: --verify-only against a real PostgreSQL target (STYX_TEST_DATABASE_URL at Alembic head)."""
import asyncio
import hashlib

import pytest
import sqlalchemy as sa
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db_migrate import migrate
from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source, raw_exec

pytestmark = pytest.mark.pg_only


async def _q(url, sql, scalar=False):
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        async with eng.begin() as c:
            r = await c.execute(sa.text(sql))
            return r.scalar() if scalar else None
    finally:
        await eng.dispose()


async def test_verify_only_reports_mismatch(tmp_path, capsys, scratch_url):
    """Equal row counts, one changed target field -> checksum-only mismatch (exit 3)."""
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src = await make_source(tmp_path / "s.db")
    eng = create_async_engine(scratch_url, poolclass=NullPool)
    try:
        await migrate(eng)
    finally:
        await eng.dispose()
    raw_exec(src, "INSERT INTO system_settings (key, value, updated_at) "
                  "VALUES ('k', '\"v\"', '2026-01-01 00:00:00')")
    await _q(scratch_url, "INSERT INTO system_settings (key, value, updated_at) "
                          "VALUES ('k', '\"v\"', '2026-01-01 00:00:00')")
    argv = ["--source", str(src), "--target", scratch_url, "--verify-only"]
    assert await asyncio.to_thread(tool.main, argv) == 0
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    await _q(scratch_url, "UPDATE system_settings SET value = '\"changed\"' WHERE key = 'k'")
    capsys.readouterr()
    assert await asyncio.to_thread(tool.main, argv) == 3
    out = capsys.readouterr().out
    assert "MISMATCH" in out and "system_settings" in out
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
    val = await _q(scratch_url, "SELECT value::text FROM system_settings WHERE key = 'k'", scalar=True)
    assert "changed" in val  # verify performed no writes


async def _migrated(url):
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        await migrate(eng)
    finally:
        await eng.dispose()


async def test_24_orphan_source_exits_2_target_empty(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    await _migrated(scratch_url)
    src = await make_source(tmp_path / "s.db")
    raw_exec(src, "INSERT INTO refresh_tokens (jti, user_id, family_id, expires_at, revoked, session_only, "
                  "created_at) VALUES ('j','ghost','','2026-01-01 00:00:00','0','0','2026-01-01 00:00:00')")
    argv = ["--source", str(src), "--target", scratch_url]
    assert await asyncio.to_thread(tool.main, argv) == 2
    assert await _q(scratch_url, "SELECT count(*) FROM refresh_tokens", scalar=True) == 0


async def test_26_dry_run_exits_0_target_empty(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    await _migrated(scratch_url)
    src = await make_source(tmp_path / "s.db")
    argv = ["--source", str(src), "--target", scratch_url, "--dry-run"]
    assert await asyncio.to_thread(tool.main, argv) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM refresh_tokens", scalar=True) == 0


# ---- single-transaction copy (tests 17-23, 25, 28, 29) ----
from app.tools import migrate_copy  # noqa: E402
from app.tools.migrate_checksum import checksum  # noqa: E402

NOW = "2026-01-01 00:00:00.000000"
SEQ_TABLES = ("session_events", "audit_log", "workstation_access")


def _setting(path, key="k", val='"v"'):
    raw_exec(path, "INSERT INTO system_settings (key, value, updated_at) VALUES (?,?,?)", (key, val, NOW))


def _sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


async def _dst_sums(url):
    eng = create_async_engine(url, poolclass=NullPool)
    try:
        return await checksum(eng)
    finally:
        await eng.dispose()


async def _setup(tmp_path, url, rows=1):
    await _migrated(url)
    src = await make_source(tmp_path / "s.db")
    for i in range(rows):
        _setting(src, f"k{i}")
    return src, ["--source", str(src), "--target", url]


def test_sequence_tables_derived_from_metadata():
    names = {t.name for t in migrate_copy.sequence_tables()}
    assert names == set(SEQ_TABLES)


async def test_17_full_copy_source_unchanged(tmp_path, scratch_url, capsys):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url, rows=3)
    before = _sha(src)
    assert await asyncio.to_thread(tool.main, argv) == 0
    assert _sha(src) == before
    assert await _q(scratch_url, "SELECT count(*) FROM system_settings", scalar=True) == 3
    assert await asyncio.to_thread(tool.main, argv + ["--verify-only"]) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM alembic_version", scalar=True) == 1


async def test_18_sequences_reset_no_pk_clash(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    raw_exec(src, "INSERT INTO audit_log (id, ts, action) VALUES (41, ?, 'x')", (NOW,))
    assert await asyncio.to_thread(tool.main, argv) == 0
    await _q(scratch_url, "INSERT INTO audit_log (ts, action) VALUES (now(), 'y')")
    assert await _q(scratch_url, "SELECT max(id) FROM audit_log", scalar=True) == 42
    # empty sequenced table: first insert gets id 1
    await _q(scratch_url, "INSERT INTO session_events (ts) VALUES (now())")
    assert await _q(scratch_url, "SELECT min(id) FROM session_events", scalar=True) == 1


async def test_19_rerun_is_noop(tmp_path, scratch_url, capsys):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    assert await asyncio.to_thread(tool.main, argv) == 0
    capsys.readouterr()
    before = await _dst_sums(scratch_url)
    assert await asyncio.to_thread(tool.main, argv) == 0
    assert "already migrated" in capsys.readouterr().out
    assert await _dst_sums(scratch_url) == before


async def test_20_nonempty_refused_without_replace(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    await _q(scratch_url, "INSERT INTO system_settings (key, value, updated_at) VALUES ('other','1',now())")
    before = await _dst_sums(scratch_url)
    assert await asyncio.to_thread(tool.main, argv) == 2
    assert await _dst_sums(scratch_url) == before


async def test_21_replace_overwrites(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    await _q(scratch_url, "INSERT INTO system_settings (key, value, updated_at) VALUES ('other','1',now())")
    assert await asyncio.to_thread(tool.main, argv + ["--replace"]) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM system_settings WHERE key='other'", scalar=True) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM alembic_version", scalar=True) == 1
    assert await asyncio.to_thread(tool.main, argv + ["--verify-only"]) == 0


async def test_22_seeded_target_needs_replace(tmp_path, scratch_url):
    """App started on PG once: seed rows exist; plain run refused, --replace works."""
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    await _q(scratch_url, "INSERT INTO system_settings (key, value, updated_at) VALUES ('seed','1',now())")
    assert await asyncio.to_thread(tool.main, argv) == 2
    assert await asyncio.to_thread(tool.main, argv + ["--replace"]) == 0


async def test_23_verify_mismatch_rolls_back(tmp_path, scratch_url, monkeypatch):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    before_src = _sha(src)
    real = migrate_copy.target_checksum

    async def bad(conn, tables):
        out = await real(conn, tables)
        name = next(iter(out))
        out[name] = (out[name][0], "0" * 64)
        return out

    monkeypatch.setattr(migrate_copy, "target_checksum", bad)
    assert await asyncio.to_thread(tool.main, argv) == 3
    assert await _q(scratch_url, "SELECT count(*) FROM system_settings", scalar=True) == 0
    assert _sha(src) == before_src


async def test_25_drop_orphans_copies_rest(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    raw_exec(src, "INSERT INTO refresh_tokens (jti, user_id, family_id, expires_at, revoked, session_only, "
                  "created_at) VALUES ('j','ghost','','2026-01-01 00:00:00','0','0','2026-01-01 00:00:00')")
    assert await asyncio.to_thread(tool.main, argv + ["--drop-orphans"]) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM refresh_tokens", scalar=True) == 0
    assert await _q(scratch_url, "SELECT count(*) FROM system_settings", scalar=True) == 1


async def test_28_target_version_mismatch_exit_2(tmp_path, scratch_url):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    src, argv = await _setup(tmp_path, scratch_url)
    await _q(scratch_url, "UPDATE alembic_version SET version_num = 'bogus'")
    assert await asyncio.to_thread(tool.main, argv + ["--replace"]) == 2
    assert await _q(scratch_url, "SELECT count(*) FROM system_settings", scalar=True) == 0


async def test_29_password_never_leaks(tmp_path, scratch_url, capsys, caplog):
    if not scratch_url.startswith("postgresql"):
        pytest.skip("needs PostgreSQL")
    from sqlalchemy.engine import make_url
    src, _ = await _setup(tmp_path, scratch_url)
    secret = "s3cr3t-xyz"
    for url in (make_url(scratch_url).set(password=secret).render_as_string(hide_password=False), scratch_url):
        await asyncio.to_thread(tool.main, ["--source", str(src), "--target", url, "--replace"])
    out = capsys.readouterr()
    assert secret not in out.out + out.err + caplog.text
