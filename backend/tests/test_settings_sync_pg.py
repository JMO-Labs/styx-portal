"""Needs a real Postgres: set TEST_PG_URL=postgresql://user:pw@host/db."""
import asyncio
import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.settings_store import SettingsService
from app.services.settings_sync import settings_sync_loop

PG = os.environ.get("TEST_PG_URL")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not PG, reason="TEST_PG_URL not set")]


@pytest.fixture
async def factory():
    engine = create_async_engine(PG.replace("postgresql://", "postgresql+asyncpg://", 1))
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM system_settings"))
    await engine.dispose()


async def test_write_on_a_visible_on_b_within_5s(factory):
    a, b = SettingsService(), SettingsService()
    task = asyncio.create_task(settings_sync_loop(factory, b, interval=0.2))
    try:
        async with factory() as s:
            await a.set(s, "LOCKOUT_THRESHOLD", 42, None)
            await s.commit()
        for _ in range(50):
            if b.get("LOCKOUT_THRESHOLD") == 42:
                break
            await asyncio.sleep(0.1)
        assert b.get("LOCKOUT_THRESHOLD") == 42
        async with factory() as s:
            await a.reset(s, "LOCKOUT_THRESHOLD", None)
            await s.commit()
        for _ in range(50):
            if b.get("LOCKOUT_THRESHOLD") != 42:
                break
            await asyncio.sleep(0.1)
        assert b.get("LOCKOUT_THRESHOLD") != 42
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
