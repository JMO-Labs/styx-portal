"""Leader elector edge paths with a mocked asyncpg connection (no Postgres needed)."""
import asyncio
from unittest.mock import MagicMock

from app.config import Settings
from app.services.leader import LeaderElector


def _el(**kw):
    s = Settings(DATABASE_URL="postgresql://u:p@h/d", LEADER_DATABASE_URL="postgresql://u:p@h/d",
                 LEADER_RETRY_S=0.02, LEADER_HEARTBEAT_S=0.02,
                 LEADER_HEARTBEAT_TIMEOUT_S=0.05, LEADER_FENCE_S=0.5, **kw)
    return LeaderElector(s)


def _conn(fetchval):
    c = MagicMock()
    c.fetchval = fetchval
    c.get_server_pid.return_value = 4242
    return c


async def test_backend_pid_none_without_conn_and_set_with_conn():
    el = _el()
    assert el.backend_pid is None
    el._conn = _conn(None)
    assert el.backend_pid == 4242


async def test_connect_error_is_candidate_failure_then_retries(monkeypatch):
    attempts = []

    async def connect(*a, **k):
        attempts.append(1)
        raise OSError("refused")

    monkeypatch.setattr("asyncpg.connect", connect)
    el = _el()
    t = asyncio.create_task(el.run())
    while len(attempts) < 2:
        await asyncio.sleep(0.01)
    assert not el.is_leader
    await el.stop()
    await t


async def test_lock_not_granted_terminates_conn_without_unlock(monkeypatch):
    sqls, conns = [], []

    async def fetchval(sql, *a):
        sqls.append(sql)
        return False

    async def connect(*a, **k):
        conns.append(_conn(fetchval))
        return conns[-1]

    monkeypatch.setattr("asyncpg.connect", connect)
    el = _el()
    t = asyncio.create_task(el.run())
    while not conns or not conns[0].terminate.called:
        await asyncio.sleep(0.01)
    assert not el.is_leader
    assert not any("unlock" in s for s in sqls)
    await el.stop()
    await t


async def test_healthy_heartbeat_keeps_leadership_and_unlock_error_is_swallowed(monkeypatch):
    beats, conns = [], []

    async def fetchval(sql, *a):
        if "unlock" in sql:
            raise RuntimeError("conn gone")
        if "pg_locks" in sql:
            beats.append(1)
        return True

    async def connect(*a, **k):
        conns.append(_conn(fetchval))
        return conns[-1]

    monkeypatch.setattr("asyncpg.connect", connect)
    el, elected, lost = _el(), asyncio.Event(), asyncio.Event()
    t = asyncio.create_task(el.run(on_elected=elected.set, on_lost=lost.set))
    await asyncio.wait_for(elected.wait(), 2)
    while len(beats) < 2:
        await asyncio.sleep(0.01)
    assert el.is_leader and not lost.is_set()
    await el.stop()  # unlock raises; must not propagate
    await t
    conns[0].terminate.assert_called()


async def test_stop_when_not_running_closes_connection_with_unlock():
    el = _el()
    unlocked = []

    async def fetchval(sql, *a):
        unlocked.append(sql)
        return True

    c = _conn(fetchval)
    el._conn, el._leader = c, True
    await el.stop()
    assert any("unlock" in s for s in unlocked)
    c.terminate.assert_called_once()
    assert el._conn is None and not el.is_leader
