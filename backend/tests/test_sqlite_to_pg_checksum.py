"""Canonical row checksum (tests 1-4) and verify() over two engines (no writes)."""
import hashlib
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from app.tools import migrate_checksum as mc
from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source

META = sa.MetaData()
T = sa.Table(
    "t", META,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String),
    sa.Column("flag", sa.Boolean),
    sa.Column("score", sa.Float),
    sa.Column("at", sa.DateTime),
    sa.Column("blob", sa.JSON),
)


async def _engine(tmp_path, name, rows):
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / name}")
    async with eng.begin() as c:
        await c.run_sync(META.create_all)
        for r in rows:
            await c.execute(T.insert().values(**r))
    return eng


ROWS = [
    {"id": 1, "name": "a", "flag": True, "score": 1.5, "at": datetime(2026, 1, 2, 3, 4, 5), "blob": {"b": 1, "a": 2}},
    {"id": 2, "name": "b", "flag": False, "score": 2.0, "at": None, "blob": None},
]


def test_canonical_row_sorts_keys_and_formats_types():
    row = {"id": 1, "name": "a", "flag": 1, "score": 2.0,
           "at": datetime(2026, 1, 2, 3, 4, 5), "blob": {"z": 1, "a": [1]}}
    out = mc.canonical_row(T, row)
    assert out == ('{"at":"2026-01-02T03:04:05","blob":{"a":[1],"z":1},"flag":true,'
                   '"id":1,"name":"a","score":"2.0"}')


async def test_checksum_independent_of_insert_order(tmp_path):
    a = await _engine(tmp_path, "a.db", ROWS)
    b = await _engine(tmp_path, "b.db", list(reversed(ROWS)))
    try:
        assert await mc.checksum(a, [T]) == await mc.checksum(b, [T])
    finally:
        await a.dispose()
        await b.dispose()


async def test_checksum_detects_single_field_change(tmp_path):
    a = await _engine(tmp_path, "a.db", ROWS)
    b = await _engine(tmp_path, "b.db", ROWS)
    try:
        async with b.begin() as c:
            await c.execute(T.update().where(T.c.id == 2).values(name="B"))
        ra, rb = await mc.checksum(a, [T]), await mc.checksum(b, [T])
        assert ra["t"][0] == rb["t"][0] == 2 and ra["t"][1] != rb["t"][1]
    finally:
        await a.dispose()
        await b.dispose()


def test_sqlite_int_bool_hashes_equal_pg_bool():
    assert mc.canonical_row(T, {"id": 1, "flag": 1}) == mc.canonical_row(T, {"id": 1, "flag": True})
    assert '"flag":true' in mc.canonical_row(T, {"id": 1, "flag": 1})


def test_tables_exclude_alembic_version():
    names = [t.name for t in mc.copy_tables()]
    assert "alembic_version" not in names and names


async def test_verify_match_and_mismatch_and_source_untouched(tmp_path, capsys):
    src = await make_source(tmp_path / "s.db")
    dst = await make_source(tmp_path / "d.db")
    before = hashlib.sha256(src.read_bytes()).hexdigest()
    s, d = tool.open_source(src), create_async_engine(f"sqlite+aiosqlite:///{dst}")
    try:
        assert await tool.verify(s, d) == 0
        out = capsys.readouterr().out
        assert "rows_src" in out and "users" in out
        async with d.begin() as c:
            await c.execute(sa.text(
                "INSERT INTO system_settings (key, value, updated_at) VALUES ('k', '1', '2026-01-01 00:00:00')"))
        assert await tool.verify(s, d) == 3
    finally:
        await s.dispose()
        await d.dispose()
    assert hashlib.sha256(src.read_bytes()).hexdigest() == before
