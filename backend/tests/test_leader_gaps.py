"""Mocked-connection coverage for leader.py error paths (no Postgres needed)."""
import asyncio
from unittest.mock import MagicMock

from app.config import Settings
from app.services.leader import LeaderElector


def _el():
    s = Settings(DATABASE_URL="postgresql://u:p@h/d", LEADER_DATABASE_URL="postgresql://u:p@h/d",
                 LEADER_RETRY_S=0.05, LEADER_HEARTBEAT_S=0.02,
                 LEADER_HEARTBEAT_TIMEOUT_S=0.05, LEADER_FENCE_S=0.1)
    return LeaderElector(s)


def test_backend_pid_none_without_conn_and_pid_with_conn():
    el = _el()
    assert el.backend_pid is None
    el._conn = MagicMock()
    el._conn.get_server_pid.return_value = 4242
    assert el.backend_pid == 4242


async def test_try_acquire_connect_error_returns_false(monkeypatch):
    async def connect(*a, **k):
        raise OSError("down")

    monkeypatch.setattr("asyncpg.connect", connect)
    el = _el()
    assert await el._try_acquire() is False
    assert el._conn is None and not el.is_leader


async def test_try_acquire_lock_held_closes_conn(monkeypatch):
    c = MagicMock()

    async def fetchval(*a):
        return False

    c.fetchval = fetchval

    async def connect(*a, **k):
        return c

    monkeypatch.setattr("asyncpg.connect", connect)
    el = _el()
    assert await el._try_acquire() is False
    c.terminate.assert_called_once()


async def test_close_swallows_unlock_failure():
    el = _el()
    c = MagicMock()

    async def fetchval(*a):
        raise RuntimeError("gone")

    c.fetchval = fetchval
    el._conn, el._leader = c, True
    await el._close(unlock=True)
    c.terminate.assert_called_once()
    assert el._conn is None and not el._leader


async def test_hold_healthy_heartbeat_keeps_leadership():
    el = _el()
    c = MagicMock()

    async def fetchval(*a):
        return True

    c.fetchval = fetchval
    el._conn, el._leader = c, True
    task = asyncio.create_task(el._hold())
    await asyncio.sleep(0.25)  # > FENCE_S: only a refreshed last_ok keeps it alive
    assert not task.done() and el.is_leader
    el._stop.set()
    await asyncio.wait_for(task, 1)


async def test_stop_when_not_running_closes_and_unlocks():
    el = _el()
    c = MagicMock()
    sqls = []

    async def fetchval(sql, *a):
        sqls.append(sql)

    c.fetchval = fetchval
    el._conn, el._leader = c, True
    await el.stop()
    assert any("unlock" in s for s in sqls)
    c.terminate.assert_called_once()
