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
