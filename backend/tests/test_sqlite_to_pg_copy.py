"""pg_only: --verify-only against a real PostgreSQL target (STYX_TEST_DATABASE_URL at Alembic head)."""
import asyncio
import hashlib
import os

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source

pytestmark = pytest.mark.pg_only
PG_URL = os.environ.get("STYX_TEST_DATABASE_URL", "")


async def _setting(sql):
    eng = create_async_engine(PG_URL)
    try:
        async with eng.begin() as c:
            await c.execute(sa.text(sql))
    finally:
        await eng.dispose()


def test_verify_only_reports_mismatch(tmp_path, capsys):
    src = asyncio.run(make_source(tmp_path / "s.db"))
    asyncio.run(_setting("DELETE FROM system_settings"))
    argv = ["--source", str(src), "--target", PG_URL, "--verify-only"]
    assert tool.main(argv) == 0
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    asyncio.run(_setting("INSERT INTO system_settings (key, value, updated_at) "
                         "VALUES ('k', '\"v\"', now())"))
    capsys.readouterr()
    try:
        assert tool.main(argv) == 3
        out = capsys.readouterr().out
        assert "MISMATCH" in out and "system_settings" in out
        assert hashlib.sha256(src.read_bytes()).hexdigest() == before
        assert asyncio.run(_count()) == 1  # target untouched by verify
    finally:
        asyncio.run(_setting("DELETE FROM system_settings"))


async def _count():
    eng = create_async_engine(PG_URL)
    try:
        async with eng.connect() as c:
            return (await c.execute(sa.text("SELECT count(*) FROM system_settings"))).scalar()
    finally:
        await eng.dispose()
