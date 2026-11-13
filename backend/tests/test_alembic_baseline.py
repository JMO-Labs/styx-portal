from alembic.script import ScriptDirectory
from sqlmodel import SQLModel

from app.db_migrate import alembic_config, migrate
from tests.db_helpers import diff_vs_models, downgrade_base, scalar, table_names


def test_naming_convention_set():
    assert {"ix", "uq", "ck", "fk", "pk"} <= set(SQLModel.metadata.naming_convention)


def test_single_head():
    heads = ScriptDirectory.from_config(alembic_config()).get_heads()
    assert heads == ["0019_session_takeover"]


async def test_upgrade_head_matches_models(scratch_engine):
    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert await conn.run_sync(diff_vs_models) == []
    assert await scalar(scratch_engine, "SELECT version_num FROM alembic_version") == "0019_session_takeover"


async def test_downgrade_base_then_upgrade(scratch_engine):
    await migrate(scratch_engine)
    await downgrade_base(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert await conn.run_sync(table_names) <= {"alembic_version"}
    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        assert "users" in await conn.run_sync(table_names)


async def test_group_tier_columns_up_and_down(scratch_engine):
    from alembic import command
    from sqlalchemy import inspect

    cols = ("tier_resolution", "tier_fps", "tier_hidpi", "tier_cpu", "tier_memory")
    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        have = await conn.run_sync(lambda c: {x["name"]: x for x in inspect(c).get_columns("groups")})
    assert all(c in have and have[c]["nullable"] for c in cols)

    async with scratch_engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(alembic_config(c), "0003_user_lifecycle"))
    async with scratch_engine.connect() as conn:
        have = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("groups")})
    assert not set(cols) & have


async def test_notices_and_last_used_up_and_down(scratch_engine):
    from alembic import command
    from sqlalchemy import inspect

    await migrate(scratch_engine)
    async with scratch_engine.connect() as conn:
        notice_cols, prof = await conn.run_sync(
            lambda c: (
                {x["name"] for x in inspect(c).get_columns("notices")},
                {x["name"]: x for x in inspect(c).get_columns("user_profiles")},
            )
        )
        assert {"id", "user_id", "kind", "key", "message", "due_at", "created_at",
                "dismissed_at"} <= notice_cols
        assert prof["last_used_at"]["nullable"]

    async with scratch_engine.begin() as conn:
        await conn.run_sync(lambda c: command.downgrade(alembic_config(c), "0012_instance_recycle_deadline"))
    async with scratch_engine.connect() as conn:
        assert "notices" not in await conn.run_sync(table_names)
        cols = await conn.run_sync(lambda c: {x["name"] for x in inspect(c).get_columns("user_profiles")})
        assert "last_used_at" not in cols
    await migrate(scratch_engine)
