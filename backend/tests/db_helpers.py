"""Scratch databases for migration/startup tests (SQLite file or a throwaway PG database)."""
import pytest
from alembic import command
import sqlalchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

from app.db_migrate import alembic_config
from tests.conftest import IS_PG, TEST_DB_URL


async def _pg_admin(sql: str) -> None:
    eng = create_async_engine(TEST_DB_URL, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    async with eng.connect() as conn:
        await conn.execute(sqlalchemy.text(sql))
    await eng.dispose()


@pytest.fixture
async def scratch_url(tmp_path):
    if not IS_PG:
        yield f"sqlite+aiosqlite:///{tmp_path / 'styx.db'}"
        return
    url = make_url(TEST_DB_URL)
    name = f"{url.database}_scratch"
    await _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    await _pg_admin(f'CREATE DATABASE "{name}"')
    yield url.set(database=name).render_as_string(hide_password=False)
    await _pg_admin(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
async def scratch_engine(scratch_url):
    eng = create_async_engine(scratch_url, poolclass=NullPool)
    yield eng
    await eng.dispose()


def diff_vs_models(sync_conn):
    return compare_metadata(MigrationContext.configure(sync_conn), SQLModel.metadata)


def table_names(sync_conn) -> set[str]:
    return set(inspect(sync_conn).get_table_names())


async def scalar(engine, sql: str):
    async with engine.connect() as conn:
        return (await conn.execute(sqlalchemy.text(sql))).scalar()


async def downgrade_base(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(alembic_config(c), "base"))
