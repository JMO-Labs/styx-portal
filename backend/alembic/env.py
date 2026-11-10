"""Async Alembic env. The app passes its own connection via config.attributes."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table)
from app.db_types import UTCDateTime

config = context.config
target_metadata = SQLModel.metadata


def render_item(type_, obj, autogen_context):
    """Render UTCDateTime as plain sa.DateTime so revisions never import app code."""
    if type_ == "type" and isinstance(obj, UTCDateTime):
        return "sa.DateTime()"
    return False


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_item=render_item,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite cannot ALTER/DROP columns
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    from app.config import Settings

    engine = create_async_engine(Settings().DATABASE_URL, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; run against a database.")

connection = config.attributes.get("connection")
if connection is None:  # CLI
    if config.config_file_name:
        fileConfig(config.config_file_name)
    asyncio.run(run_async_migrations())
else:  # app startup / tests: never touch app logging
    do_run_migrations(connection)
