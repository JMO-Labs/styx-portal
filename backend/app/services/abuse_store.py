"""Async abuse-state store: login lockouts, IP failure counts, rate windows.

Callers own the fail policy: when a store call raises, lockout/ban/strict-auth checks
deny and the default rate limit allows (with a warning).
"""
from functools import lru_cache
from typing import Callable, Protocol

from app.config import Settings
from app.middleware.rate_limit import SlidingWindow
from app.services.abuse import IpFailTracker, LoginLockout, fail_tracker, login_lockout

import logging

_settings = Settings()
logger = logging.getLogger("styx-portal")


class AbuseStore(Protocol):
    async def is_locked(self, username: str, ip: str) -> bool: ...
    async def locked_for(self, username: str) -> float: ...
    async def record_fail(self, username: str, ip: str, threshold: int, duration: int) -> bool: ...
    async def clear(self, username: str, ip: str) -> None: ...
    async def clear_user(self, username: str) -> None: ...
    async def throttled(self, username: str, threshold: int, duration: int) -> bool: ...
    async def device_blocked(self, rnd: str) -> bool: ...
    async def device_fail(self, rnd: str, threshold: int, duration: int) -> None: ...
    async def device_clear(self, rnd: str) -> None: ...
    async def ip_fail(self, ip: str, threshold: int, window: int) -> bool: ...
    async def rate_allow(self, key: str, limit: int, window: int) -> bool: ...


class MemoryAbuseStore:
    """Per-process store wrapping the in-memory trackers (single-host SQLite deployments)."""

    def __init__(self, lockout: LoginLockout | None = None,
                 tracker: IpFailTracker | None = None,
                 now: Callable[[], float] | None = None) -> None:
        self._lockout = lockout if lockout is not None else login_lockout
        self._tracker = tracker if tracker is not None else fail_tracker
        self._clock = now
        self._windows: dict[tuple[int, int], SlidingWindow] = {}

    def _now(self) -> float | None:
        return self._clock() if self._clock else None

    async def is_locked(self, username, ip):
        return self._lockout.is_locked(username, ip, now=self._now())

    async def locked_for(self, username):
        return self._lockout.locked_for(username, now=self._now())

    async def record_fail(self, username, ip, threshold, duration):
        return self._lockout.record_fail(username, ip, threshold, duration, now=self._now())

    async def clear(self, username, ip):
        self._lockout.clear(username, ip)

    async def clear_user(self, username):
        self._lockout.clear_user(username)

    async def throttled(self, username, threshold, duration):
        return self._lockout.throttled(username, threshold, duration, now=self._now())

    async def device_blocked(self, rnd):
        return self._lockout.device_blocked(rnd, now=self._now())

    async def device_fail(self, rnd, threshold, duration):
        self._lockout.device_fail(rnd, threshold, duration, now=self._now())

    async def device_clear(self, rnd):
        self._lockout.device_clear(rnd)

    async def ip_fail(self, ip, threshold, window):
        self._tracker.threshold, self._tracker.window = threshold, window
        now = self._now()
        return self._tracker.record(ip) if now is None else self._tracker.record(ip, now=now)

    def window_for(self, limit: int, window: int) -> SlidingWindow:
        w = self._windows.get((limit, window))
        if w is None:
            w = self._windows[(limit, window)] = SlidingWindow(limit, window)
        return w

    async def rate_allow(self, key, limit, window):
        return self.window_for(limit, window).allow(key, now=self._now())


@lru_cache(maxsize=1)
def get_abuse_store() -> AbuseStore:
    """PgAbuseStore on Postgres (state shared across replicas); memory on SQLite."""
    if _settings.DATABASE_URL.startswith("postgresql"):
        from app.database import engine
        from app.services.abuse_store_pg import PgAbuseStore
        return PgAbuseStore(engine)
    if not _settings.DATABASE_URL.startswith("sqlite"):
        logger.warning("no shared abuse store for this database; using per-process memory")
    return MemoryAbuseStore()
