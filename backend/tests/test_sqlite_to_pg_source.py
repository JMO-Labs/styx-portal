import sqlalchemy
import pytest
from sqlalchemy.exc import OperationalError

from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source, raw_exec


def test_source_url_is_readonly_uri_absolute(tmp_path):
    url = tool.source_url(tmp_path / "a.db")
    assert url.startswith(f"sqlite+aiosqlite:///file:{tmp_path}")
    assert "mode=ro" in url and "uri=true" in url


async def test_source_engine_rejects_writes(tmp_path):
    src = await make_source(tmp_path / "s.db")
    eng = tool.open_source(src)
    try:
        async with eng.begin() as conn:
            with pytest.raises(OperationalError):
                await conn.execute(sqlalchemy.text("DELETE FROM alembic_version"))
    finally:
        await eng.dispose()


async def test_source_engine_rejects_insert(tmp_path):
    src = await make_source(tmp_path / "s.db")
    eng = tool.open_source(src)
    try:
        async with eng.begin() as conn:
            with pytest.raises(OperationalError):
                await conn.execute(sqlalchemy.text("INSERT INTO alembic_version VALUES ('x')"))
    finally:
        await eng.dispose()


async def test_version_gate_ok(tmp_path):
    src = await make_source(tmp_path / "s.db")
    eng = tool.open_source(src)
    try:
        await tool.check_version(eng)
    finally:
        await eng.dispose()


async def test_version_gate_unstamped(tmp_path):
    src = tmp_path / "u.db"
    raw_exec(src, "CREATE TABLE t (x INTEGER)")
    eng = tool.open_source(src)
    try:
        with pytest.raises(tool.PreflightError, match="start the new release once on SQLite"):
            await tool.check_version(eng)
    finally:
        await eng.dispose()


async def test_version_gate_mismatch(tmp_path):
    src = await make_source(tmp_path / "s.db")
    raw_exec(src, "UPDATE alembic_version SET version_num = 'old'")
    eng = tool.open_source(src)
    try:
        with pytest.raises(tool.PreflightError, match="start the new release once on SQLite"):
            await tool.check_version(eng)
    finally:
        await eng.dispose()
