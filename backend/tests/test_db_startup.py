import os
import sqlite3
import stat
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import sqlalchemy
from sqlmodel import SQLModel

from app import db_migrate
from app.db_migrate import migrate
from tests.db_helpers import diff_vs_models, scalar, table_names

FIXTURES = Path(__file__).parent / "fixtures"
HEAD = "0002_abuse_tables"

# Drift a legacy (ALTER-built) SQLite DB keeps after the stamp. SQLite is type-lax, so
# these are harmless. Expected; do not "fix" them in the baseline.
ALLOWED_DIFF_KINDS = {"modify_nullable", "modify_type"}
# Old releases had session_events.instance_id -> instances FK; SQLite never enforced it.
ALLOWED_REMOVED_FKS = {"session_events"}


def _db_path(engine) -> Path:
    return Path(engine.url.database)


def _bak(engine) -> Path:
    return Path(f"{engine.url.database}.pre-alembic.bak")


def _kinds(diffs) -> set[str]:
    out = set()
    for d in diffs:
        for item in (d if isinstance(d, list) else [d]):
            if item[0] == "remove_fk" and item[1].parent.name in ALLOWED_REMOVED_FKS:
                continue
            out.add(item[0])
    return out


async def test_fresh_db_runs_upgrade_head(scratch_engine):
    await migrate(scratch_engine)
    assert await scalar(scratch_engine, "SELECT version_num FROM alembic_version") == HEAD
    async with scratch_engine.connect() as conn:
        assert "users" in await conn.run_sync(table_names)
    if scratch_engine.url.get_backend_name() == "sqlite":
        assert not _bak(scratch_engine).exists()


@pytest.mark.sqlite_only
async def test_legacy_sqlite_is_backed_up_and_stamped(scratch_engine):
    async with scratch_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.execute(sqlalchemy.text(
            "INSERT INTO banned_ip (ip, reason, banned_at, expires_at) "
            "VALUES ('1.2.3.4', 'x', '2026-01-01 00:00:00', '2027-01-01 00:00:00')"))
    before = await scalar(scratch_engine, "SELECT reason FROM banned_ip")
    await migrate(scratch_engine)
    bak = _bak(scratch_engine)
    assert bak.exists()
    assert stat.S_IMODE(os.stat(bak).st_mode) == 0o600
    # backup holds the pre-migration data and no version table
    with sqlite3.connect(bak) as c:
        assert c.execute("SELECT reason FROM banned_ip").fetchone()[0] == before
        assert not c.execute(
            "SELECT 1 FROM sqlite_master WHERE name='alembic_version'").fetchone()
    assert await scalar(scratch_engine, "SELECT version_num FROM alembic_version") == HEAD
    assert await scalar(scratch_engine, "SELECT reason FROM banned_ip") == before


@pytest.mark.sqlite_only
@pytest.mark.parametrize("fixture", ["legacy_v1.sql", "legacy_v2.sql"])
async def test_legacy_old_schema_gets_missing_columns(scratch_engine, fixture):
    with sqlite3.connect(_db_path(scratch_engine)) as c:
        c.executescript((FIXTURES / fixture).read_text())
        users_before = c.execute("SELECT id, username, email, password_hash, role "
                                 "FROM users ORDER BY id").fetchall()
        tpl_before = c.execute("SELECT id, name, image FROM service_templates").fetchall()
    await migrate(scratch_engine)
    with sqlite3.connect(_db_path(scratch_engine)) as c:
        cols = {r[1] for r in c.execute("PRAGMA table_info(users)")}
        assert {"token_version", "matrix_serial", "failed_count"} <= cols
        assert "privileged" in {r[1] for r in c.execute("PRAGMA table_info(service_templates)")}
        assert c.execute("SELECT id, username, email, password_hash, role "
                         "FROM users ORDER BY id").fetchall() == users_before
        assert c.execute("SELECT id, name, image FROM service_templates").fetchall() == tpl_before
        assert c.execute("SELECT version_num FROM alembic_version").fetchone()[0] == HEAD
    async with scratch_engine.connect() as conn:
        diffs = await conn.run_sync(diff_vs_models)
    assert _kinds(diffs) <= ALLOWED_DIFF_KINDS, diffs


async def test_stamped_db_skips_legacy_migrations(scratch_engine, monkeypatch):
    await migrate(scratch_engine)
    spy = AsyncMock()
    monkeypatch.setattr(db_migrate, "_run_migrations", spy)
    await migrate(scratch_engine)
    spy.assert_not_called()
    if scratch_engine.url.get_backend_name() == "sqlite":
        assert not _bak(scratch_engine).exists()


@pytest.mark.sqlite_only
async def test_init_db_idempotent(scratch_engine):
    async with scratch_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    await migrate(scratch_engine)
    bak = _bak(scratch_engine)
    first = bak.stat().st_mtime_ns
    async with scratch_engine.connect() as conn:
        tables = await conn.run_sync(table_names)
    await migrate(scratch_engine)
    assert bak.stat().st_mtime_ns == first
    assert sorted(bak.parent.glob("*.bak")) == [bak]
    async with scratch_engine.connect() as conn:
        assert await conn.run_sync(table_names) == tables
    assert await scalar(scratch_engine, "SELECT count(*) FROM alembic_version") == 1


@pytest.mark.pg_only
async def test_pg_tables_without_version_refuses(scratch_engine):
    async with scratch_engine.begin() as conn:
        await conn.execute(sqlalchemy.text("CREATE TABLE users (id text primary key)"))
    with pytest.raises(RuntimeError, match="alembic_version"):
        await migrate(scratch_engine)


@pytest.mark.pg_only
async def test_pg_upgrade_takes_advisory_lock(scratch_engine, monkeypatch):
    seen = []
    real_upgrade = db_migrate._upgrade_head

    def upgrade(sync_conn):
        seen.append("upgrade")
        return real_upgrade(sync_conn)

    @sqlalchemy.event.listens_for(scratch_engine.sync_engine, "before_cursor_execute")
    def _log(conn, cursor, statement, *a):
        if "pg_advisory_xact_lock" in statement:
            seen.append("lock")

    monkeypatch.setattr(db_migrate, "_upgrade_head", upgrade)
    await migrate(scratch_engine)
    assert seen[:2] == ["lock", "upgrade"]
