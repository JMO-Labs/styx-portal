"""Cover fail-open/fail-closed branches around the abuse store."""
import logging
from types import SimpleNamespace

from app.models import User
from app.routers import instances, users
from app.services import abuse_store, login_flow


class _Boom:
    async def _raise(self, *a, **k):
        raise RuntimeError("store down")

    rate_allow = locked_for = clear = device_clear = _raise


async def test_create_limiter_fails_open(monkeypatch):
    monkeypatch.setattr(instances, "get_abuse_store", lambda: _Boom())
    assert await instances._create_limiter.allow("u1") is True


async def test_user_out_shows_unlocked_on_store_error(monkeypatch):
    monkeypatch.setattr(users, "get_abuse_store", lambda: _Boom())
    u = User(username="bob", email="b@x.io", role="user", password_hash="x")
    out = await users._user_out(u)
    assert out.username == "bob"
    assert out.locked_until is None


async def test_non_sqlite_falls_back_to_memory(monkeypatch, caplog):
    monkeypatch.setattr(abuse_store, "_settings", SimpleNamespace(DATABASE_URL="postgresql://x/y"))
    abuse_store.get_abuse_store.cache_clear()
    try:
        with caplog.at_level(logging.WARNING, logger="styx-portal"):
            st = abuse_store.get_abuse_store()
        assert isinstance(st, abuse_store.MemoryAbuseStore)
        assert "no shared abuse store" in caplog.text
    finally:
        abuse_store.get_abuse_store.cache_clear()


async def test_locked_trusted_device_not_locked(monkeypatch):
    class S:
        async def device_blocked(self, rnd):
            return False

    monkeypatch.setattr(abuse_store, "get_abuse_store", lambda: S())
    assert await login_flow.locked("u", "1.2.3.4", "rnd-1") is False


async def test_clear_lockout_survives_store_error(monkeypatch, caplog):
    monkeypatch.setattr(abuse_store, "get_abuse_store", lambda: _Boom())

    class Sess:
        def add(self, o):
            self.added = o

    u = User(username="bob", email="b@x.io", role="user", password_hash="x", failed_count=3)
    s = Sess()
    with caplog.at_level(logging.ERROR, logger="styx-portal"):
        await login_flow.clear_lockout(s, u, "1.2.3.4", "rnd")
    assert u.failed_count == 0 and s.added is u
    assert "abuse store failed clearing lockout" in caplog.text
