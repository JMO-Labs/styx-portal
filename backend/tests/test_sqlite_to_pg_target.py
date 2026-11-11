"""Target version gate. PG-backed tests run only when STYX_TEST_DATABASE_URL is postgres (CI test-postgres)."""
import asyncio
import os

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine

from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source

PG_URL = os.environ.get("STYX_TEST_DATABASE_URL", "")
needs_pg = pytest.mark.skipif(not PG_URL.startswith("postgresql"), reason="needs PostgreSQL")


async def _set_target_version(version):
    eng = create_async_engine(PG_URL)
    try:
        async with eng.begin() as c:
            await c.execute(sqlalchemy.text("DROP TABLE IF EXISTS alembic_version"))
            if version is not None:
                await c.execute(sqlalchemy.text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
                await c.execute(sqlalchemy.text("INSERT INTO alembic_version VALUES (:v)"), {"v": version})
    finally:
        await eng.dispose()


async def _get_target_version():
    eng = create_async_engine(PG_URL)
    try:
        async with eng.begin() as c:
            try:
                r = await c.execute(sqlalchemy.text("SELECT version_num FROM alembic_version"))
                return r.scalar()
            except sqlalchemy.exc.ProgrammingError:
                return None
    finally:
        await eng.dispose()


@pytest.fixture
def pg_version():
    original = asyncio.run(_get_target_version()) if PG_URL.startswith("postgresql") else None
    yield lambda v: asyncio.run(_set_target_version(v))
    if PG_URL.startswith("postgresql"):
        asyncio.run(_set_target_version(original))


def _run(tmp_path):
    src = asyncio.run(make_source(tmp_path / "s.db"))
    return tool.main(["--source", str(src), "--target", PG_URL])


@needs_pg
def test_target_at_head_exits_0(tmp_path, pg_version):
    pg_version(tool.code_head())
    assert _run(tmp_path) == 0


@needs_pg
def test_target_unstamped_exits_2(tmp_path, pg_version):
    pg_version(None)
    assert _run(tmp_path) == 2


@needs_pg
def test_target_mismatch_exits_2(tmp_path, pg_version):
    pg_version("old")
    assert _run(tmp_path) == 2


def test_unreachable_target_exits_2_and_hides_password(tmp_path, capsys):
    src = asyncio.run(make_source(tmp_path / "s.db"))
    bad = "postgresql+asyncpg://u:secretpw@nonexistent.invalid:5432/db"
    assert tool.main(["--source", str(src), "--target", bad]) == 2
    out = capsys.readouterr()
    assert "secretpw" not in out.out + out.err
