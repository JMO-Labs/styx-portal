"""Needs a real Postgres: set TEST_PG_URL=postgresql://user:pw@host/db."""
import asyncio
import os

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import Settings
from app.services.leader import LeaderElector

PG = os.environ.get("TEST_PG_URL")
pytestmark = [pytest.mark.pg, pytest.mark.skipif(not PG, reason="TEST_PG_URL not set")]


def _el(**kw):
    kw = {"LEADER_RETRY_S": 0.2, "LEADER_HEARTBEAT_S": 0.1, "LEADER_HEARTBEAT_TIMEOUT_S": 0.5,
          "LEADER_FENCE_S": 0.6, **kw}
    return LeaderElector(Settings(DATABASE_URL=PG, LEADER_DATABASE_URL=PG, **kw))


async def _until(pred, timeout=5):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if pred():
            return True
        await asyncio.sleep(0.05)
    return False


@pytest.fixture
async def admin():
    c = await asyncpg.connect(PG)
    yield c
    await c.close()


async def _lock_rows(admin):
    return await admin.fetch("SELECT pid FROM pg_locks WHERE locktype='advisory' "
                             "AND classid=21332 AND objid=1 AND granted")


async def test_only_one_leader_then_failover(admin):
    a, b = _el(), _el()
    ta, tb = asyncio.create_task(a.run()), asyncio.create_task(b.run())
    try:
        assert await _until(lambda: a.is_leader or b.is_leader)
        await asyncio.sleep(0.5)
        assert a.is_leader != b.is_leader
        leader, other = (a, b) if a.is_leader else (b, a)
        await admin.execute("SELECT pg_terminate_backend($1)", leader.backend_pid)
        assert await _until(lambda: other.is_leader, 0.8)
        assert not leader.is_leader
    finally:
        await a.stop()
        await b.stop()
        await asyncio.gather(ta, tb)


async def test_heartbeat_failure_self_fences_and_fires_on_lost(admin):
    lost = asyncio.Event()
    el = _el()
    t = asyncio.create_task(el.run(on_lost=lost.set))
    try:
        assert await _until(lambda: el.is_leader)
        await admin.execute("SELECT pg_terminate_backend($1)", el.backend_pid)
        await asyncio.wait_for(lost.wait(), 3)
        assert not el.is_leader
    finally:
        await el.stop()
        await t


async def test_elector_conn_is_not_a_pool_conn_and_pool_holds_no_lock(admin):
    el = _el()
    t = asyncio.create_task(el.run())
    engine = create_async_engine(PG.replace("postgresql://", "postgresql+asyncpg://", 1),
                                 pool_size=3)
    try:
        assert await _until(lambda: el.is_leader)
        from sqlalchemy import text
        pids = set()
        async with engine.connect() as c1, engine.connect() as c2:
            for c in (c1, c2):
                pids.add((await c.execute(text("SELECT pg_backend_pid()"))).scalar())
        assert el.backend_pid not in pids
        rows = await _lock_rows(admin)
        assert [r["pid"] for r in rows] == [el.backend_pid]
    finally:
        await engine.dispose()
        await el.stop()
        await t


async def test_stop_releases_lock(admin):
    el = _el()
    t = asyncio.create_task(el.run())
    assert await _until(lambda: el.is_leader)
    await el.stop()
    await t
    assert await _lock_rows(admin) == []
