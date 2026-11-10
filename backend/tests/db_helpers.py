"""Helpers for migration/startup tests (fixtures scratch_url/scratch_engine live in conftest)."""
from alembic import command
import sqlalchemy
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect
from sqlmodel import SQLModel

from app.db_migrate import alembic_config


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
