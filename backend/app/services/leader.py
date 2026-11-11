"""Leader election via a session-level Postgres advisory lock.

The lock lives on ONE dedicated asyncpg connection (never a pooled one) opened
from LEADER_DATABASE_URL, which must point straight at the primary: a pooler in
transaction mode breaks session locks. On SQLite this is a stub that is always
leader and never opens a connection.

Self-fencing: if the heartbeat fails, or nothing has succeeded for FENCE
seconds, the leader drops its connection and goes back to being a candidate.
FENCE must stay below the server-side dead-peer detection (~25 s with the
keepalive settings below) so a partitioned leader stops before another wins.
"""
import asyncio
import inspect
import logging
import time

from app.config import Settings

log = logging.getLogger("styx.leader")

LOCK_KEY = (0x5354, 1)
_KEEPALIVES = {
    "tcp_keepalives_idle": "10",
    "tcp_keepalives_interval": "5",
    "tcp_keepalives_count": "3",
    "tcp_user_timeout": "20000",
}
_ACQUIRE = "SELECT pg_try_advisory_lock($1, $2)"
_UNLOCK = "SELECT pg_advisory_unlock($1, $2)"
# Heartbeat doubles as a check that this very session still holds the lock.
_HOLDS = ("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype = 'advisory' AND granted "
          "AND pid = pg_backend_pid() AND classid = $1::oid AND objid = $2::oid "
          "AND objsubid = 2)")


async def _call(cb):
    if cb is None:
        return
    res = cb()
    if inspect.isawaitable(res):
        await res


class LeaderElector:
    def __init__(self, settings: Settings | None = None):
        self._s = settings or Settings()
        self._url = self._s.leader_url()
        self._pg = not self._url.startswith("sqlite")
        self._conn = None
        self._leader = False
        self._stop = asyncio.Event()
        self._running = False
        self._done = asyncio.Event()

    @property
    def is_leader(self) -> bool:
        return True if not self._pg else self._leader

    @property
    def backend_pid(self) -> int | None:
        return self._conn.get_server_pid() if self._conn else None

    def _dsn(self) -> str:
        return self._url.replace("+asyncpg", "", 1)

    async def _sleep(self, seconds: float) -> bool:
        """Sleep unless stopped. Returns True if stop was requested."""
        try:
            await asyncio.wait_for(self._stop.wait(), seconds)
        except asyncio.TimeoutError:
            pass
        return self._stop.is_set()

    async def run(self, on_elected=None, on_lost=None) -> None:
        self._running = True
        self._done.clear()
        try:
            await self._run(on_elected, on_lost)
        finally:
            self._running = False
            self._done.set()

    async def _run(self, on_elected, on_lost) -> None:
        if not self._pg:
            await _call(on_elected)
            await self._stop.wait()
            return
        try:
            while not self._stop.is_set():
                if await self._try_acquire():
                    log.info("leader acquired")
                    await _call(on_elected)
                    await self._hold()
                    if not self._stop.is_set():
                        log.info("leader lost")
                    await self._close(unlock=False)
                    await _call(on_lost)
                if await self._sleep(self._s.LEADER_RETRY_S):
                    break
        finally:
            await self._close(unlock=True)

    async def _try_acquire(self) -> bool:
        import asyncpg
        try:
            self._conn = await asyncpg.connect(
                self._dsn(), timeout=self._s.LEADER_HEARTBEAT_TIMEOUT_S,
                server_settings=_KEEPALIVES)
            got = await asyncio.wait_for(
                self._conn.fetchval(_ACQUIRE, *LOCK_KEY), self._s.LEADER_HEARTBEAT_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001
            log.debug("leader candidate error: %s", e)
            got = False
        if not got:
            await self._close(unlock=False)
            return False
        self._leader = True
        return True

    async def _hold(self) -> None:
        last_ok = time.monotonic()
        while not self._stop.is_set():
            if await self._sleep(self._s.LEADER_HEARTBEAT_S):
                return
            try:
                ok = await asyncio.wait_for(
                    self._conn.fetchval(_HOLDS, *LOCK_KEY), self._s.LEADER_HEARTBEAT_TIMEOUT_S)
            except Exception as e:  # noqa: BLE001
                log.debug("leader heartbeat failed: %s", e)
                ok = False
            if ok:
                last_ok = time.monotonic()
            if not ok or time.monotonic() - last_ok > self._s.LEADER_FENCE_S:
                self._leader = False
                return

    async def _close(self, unlock: bool) -> None:
        conn, self._conn = self._conn, None
        was_leader, self._leader = self._leader, False
        if conn is None:
            return
        if unlock and was_leader:
            try:
                await asyncio.wait_for(conn.fetchval(_UNLOCK, *LOCK_KEY), 2)
            except Exception:  # noqa: BLE001
                pass
        conn.terminate()

    async def stop(self) -> None:
        """Signal stop and wait for run() to finish; only its finally unlocks."""
        self._stop.set()
        if self._running:
            await self._done.wait()
        else:
            await self._close(unlock=True)


_elector: LeaderElector | None = None


def get_elector() -> LeaderElector:
    global _elector
    if _elector is None:
        _elector = LeaderElector()
    return _elector
