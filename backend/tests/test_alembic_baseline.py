from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

from app.db_migrate import alembic_config, migrate
from tests.db_helpers import diff_vs_models, downgrade_base, scalar, table_names


def test_naming_convention_set():
    assert {"ix", "uq", "ck", "fk", "pk"} <= set(SQLModel.metadata.naming_convention)


def test_single_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert heads == ["0003_posix_uids"]


async def test_upgrade_head_matches_models(scratch_engine):
    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert await conn.run_sync(diff_vs_models) == []
    assert await scalar(scratch_engine, "SELECT version_num FROM alembic_version") == "0003_posix_uids"


async def test_downgrade_base_then_upgrade(scratch_engine):
    await migrate(scratch_engine)
    await downgrade_base(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert await conn.run_sync(table_names) <= {"alembic_version"}
    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert "users" in await conn.run_sync(table_names)
