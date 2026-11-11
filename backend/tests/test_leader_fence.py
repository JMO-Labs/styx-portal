"""Fence/stop paths with a mocked connection (no Postgres needed)."""
import asyncio
from unittest.mock import MagicMock

import pytest

from app.config import Settings
from app.services.leader import LeaderElector


def _el():
    s = Settings(DATABASE_URL="postgresql://u:p@h/d", LEADER_DATABASE_URL="postgresql://u:p@h/d",
                 LEADER_RETRY_S=0.05, LEADER_HEARTBEAT_S=0.02,
                 LEADER_HEARTBEAT_TIMEOUT_S=0.05, LEADER_FENCE_S=0.1)
    return LeaderElector(s)


@pytest.mark.parametrize("mode", ["hang", "false"])
async def test_fence_fires_on_lost_and_terminates_conn(monkeypatch, mode):
    conns = []

    async def fetchval(sql, *a):
        if "try_advisory" in sql:
            return True
        if mode == "hang":
            await asyncio.sleep(10)
        return False

    async def connect(*a, **k):
        c = MagicMock()
        c.fetchval = fetchval
        conns.append(c)
        return c

    monkeypatch.setattr("asyncpg.connect", connect)
    el, lost = _el(), asyncio.Event()
    t = asyncio.create_task(el.run(on_lost=lost.set))
    try:
        await asyncio.wait_for(lost.wait(), 2)
        assert not el.is_leader
        conns[0].terminate.assert_called()
    finally:
        await el.stop()
        await t
