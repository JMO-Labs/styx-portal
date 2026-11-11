"""Needs a real Postgres: set TEST_PG_URL=postgresql://user:pw@host/db."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BannedIP, RevokedAccessToken
from app.services import token_denylist
from app.services.abuse import ban_ip
from app.services.janitor import purge_expired

PG = os.environ.get("TEST_PG_URL")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not PG, reason="TEST_PG_URL not set")]


@pytest.fixture
async def factory():
    engine = create_async_engine(PG.replace("postgresql://", "postgresql+asyncpg://", 1))
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def test_concurrent_revoke_pg(factory):
    jti = str(uuid.uuid4())
    exp = datetime.now(timezone.utc) + timedelta(minutes=5)

    async def one():
        async with factory() as s:
            await token_denylist.revoke_access(s, jti, exp)
            await s.commit()

    await asyncio.gather(*(one() for _ in range(5)))
    async with factory() as s:
        rows = (await s.exec(select(RevokedAccessToken).where(
            RevokedAccessToken.jti == jti))).all()
    assert len(rows) == 1


async def test_janitor_deletes_expired_only(factory):
    now = datetime.now(timezone.utc)
    tag = uuid.uuid4().hex[:8]
    async with factory() as s:
        await token_denylist.revoke_access(s, f"old-{tag}", now - timedelta(minutes=1))
        await token_denylist.revoke_access(s, f"new-{tag}", now + timedelta(minutes=5))
        await ban_ip(s, "198.51.100.77", "x", -60, now=now)
        await ban_ip(s, "198.51.100.78", "x", 600, now=now)
        await s.commit()
        await purge_expired(s)
        jtis = {r.jti for r in (await s.exec(select(RevokedAccessToken))).all()}
        ips = {b.ip for b in (await s.exec(select(BannedIP))).all()}
    assert f"old-{tag}" not in jtis and f"new-{tag}" in jtis
    assert "198.51.100.77" not in ips and "198.51.100.78" in ips
