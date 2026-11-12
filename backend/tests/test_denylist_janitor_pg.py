"""Needs a real Postgres: set TEST_PG_URL=postgresql://user:pw@host/db."""
import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BannedIP, RevokedAccessToken
from app.services import token_denylist
from app.services.abuse import ban_ip
from app.services.janitor import fail_window, purge_expired

PG = os.environ.get("TEST_PG_URL")
_COMMITTED_TABLES = ("revoked_access_tokens", "banned_ip", "auth_fail_events",
                     "auth_blocks", "rate_counters")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not PG, reason="TEST_PG_URL not set")]


@pytest.fixture
async def factory():
    engine = create_async_engine(PG.replace("postgresql://", "postgresql+asyncpg://", 1))
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Rows here are committed outside the per-test rollback; clear them so later
    # tests (janitor key sets, sqlite_to_pg empty-target gate) see a clean DB.
    async with engine.begin() as conn:
        for table in _COMMITTED_TABLES:
            await conn.execute(text(f"DELETE FROM {table}"))  # nosec B608 - fixed names
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


_PG_DDL = (
    "CREATE TABLE IF NOT EXISTS auth_fail_events (id BIGSERIAL PRIMARY KEY, kind VARCHAR NOT NULL,"
    " key VARCHAR NOT NULL, username VARCHAR, at TIMESTAMPTZ NOT NULL)",
    "CREATE TABLE IF NOT EXISTS auth_blocks (kind VARCHAR NOT NULL, key VARCHAR NOT NULL,"
    " username VARCHAR, until TIMESTAMPTZ NOT NULL, PRIMARY KEY (kind, key))",
    "CREATE TABLE IF NOT EXISTS rate_counters (key VARCHAR NOT NULL,"
    " window_start TIMESTAMPTZ NOT NULL, count INTEGER NOT NULL,"
    " expires_at TIMESTAMPTZ NOT NULL, PRIMARY KEY (key, window_start))",
)


async def test_janitor_purges_abuse_tables_pg(factory):
    """TIMESTAMPTZ columns accept the aware cutoff; only expired/out-of-window rows go."""
    now = datetime.now(timezone.utc)
    old, recent = now - timedelta(seconds=fail_window() + 60), now - timedelta(seconds=30)
    tag = uuid.uuid4().hex[:8]
    async with factory() as s:
        for ddl in _PG_DDL:
            await s.exec(text(ddl))
        for k, at in ((f"old-{tag}", old), (f"new-{tag}", recent)):
            await s.exec(text("INSERT INTO auth_fail_events (kind, key, at) "
                              "VALUES ('ip', :k, :at)"), params={"k": k, "at": at})
        for k, until in ((f"old-{tag}", now - timedelta(minutes=1)),
                         (f"new-{tag}", now + timedelta(minutes=5))):
            await s.exec(text("INSERT INTO auth_blocks (kind, key, until) VALUES ('user', :k, :u)"),
                         params={"k": k, "u": until})
            await s.exec(text("INSERT INTO rate_counters (key, window_start, count, expires_at) "
                              "VALUES (:k, :w, 1, :u)"), params={"k": k, "w": now, "u": until})
        await s.commit()
        await purge_expired(s, batch=1)
        for table in ("auth_fail_events", "auth_blocks", "rate_counters"):
            keys = {r[0] for r in (await s.exec(text(f"SELECT key FROM {table}"))).all()}
            assert f"old-{tag}" not in keys and f"new-{tag}" in keys, table
