import pytest

from app.services.settings_store import SettingsService
from app.services.settings_sync import settings_sync_loop, sync_once


async def test_sqlite_path_is_noop(session):
    svc = SettingsService()
    await svc.set(session, "LOCKOUT_THRESHOLD", 7, None)
    await session.commit()
    svc._overrides.clear()
    assert await sync_once(session, svc) is False   # sqlite: no reload
    assert svc._overrides == {}


async def test_loop_returns_immediately_on_sqlite(session):
    class F:
        def __call__(self):
            return self
        async def __aenter__(self):
            return session
        async def __aexit__(self, *a):
            return False
    await settings_sync_loop(F(), SettingsService(), interval=0.01)  # returns, not loops
