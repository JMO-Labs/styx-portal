import pytest

from app.services import abuse_store as store_mod
from app.services.abuse import IpFailTracker, LoginLockout
from app.services.abuse_store import MemoryAbuseStore, get_abuse_store


def _store(clock):
    return MemoryAbuseStore(LoginLockout(), IpFailTracker(3, 60), now=lambda: clock[0])


async def test_memory_store_matches_login_lockout():
    t = [100.0]
    s = _store(t)
    assert not await s.is_locked("Bob", "1.1.1.1")
    for _ in range(2):
        assert await s.record_fail("bob", "1.1.1.1", 3, 900) is False
    assert await s.record_fail("bob", "1.1.1.1", 3, 900) is True      # trip
    assert await s.is_locked("BOB", "1.1.1.1")
    assert await s.locked_for("bob") == pytest.approx(900)
    t[0] += 901
    assert not await s.is_locked("bob", "1.1.1.1")                    # expiry
    for _ in range(3):
        await s.record_fail("bob", "1.1.1.1", 3, 900)
    await s.clear("bob", "1.1.1.1")
    assert not await s.is_locked("bob", "1.1.1.1")
    for _ in range(3):
        await s.record_fail("bob", "2.2.2.2", 3, 900)
    assert await s.locked_for("bob") > 0
    await s.clear_user("bob")                                         # clear_user
    assert await s.locked_for("bob") == 0
    assert not await s.is_locked("bob", "2.2.2.2")
    # device token block
    assert not await s.device_blocked("rnd")
    for _ in range(3):
        await s.device_fail("rnd", 3, 900)
    assert await s.device_blocked("rnd")
    await s.device_clear("rnd")
    assert not await s.device_blocked("rnd")
    # distributed brake: one check per 10 s
    for i in range(3):
        await s.record_fail("amy", f"9.9.9.{i}", 10, 900)
    assert not await s.throttled("amy", 3, 900)
    assert await s.throttled("amy", 3, 900)
    t[0] += 11
    assert not await s.throttled("amy", 3, 900)


async def test_ip_fail_and_rate_allow():
    t = [0.0]
    s = _store(t)
    assert not await s.ip_fail("5.5.5.5", 2, 60)
    assert await s.ip_fail("5.5.5.5", 2, 60)
    assert await s.rate_allow("k", 1, 60)
    assert not await s.rate_allow("k", 1, 60)
    t[0] += 61
    assert await s.rate_allow("k", 1, 60)


def test_get_abuse_store_picks_memory_on_sqlite(monkeypatch):
    monkeypatch.setattr(store_mod._settings, "DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    store_mod.get_abuse_store.cache_clear()
    assert isinstance(get_abuse_store(), MemoryAbuseStore)
    assert get_abuse_store() is get_abuse_store()
