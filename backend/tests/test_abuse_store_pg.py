"""PgAbuseStore against real Postgres: two engines stand in for two replicas."""
import asyncio
import time

import pytest
import sqlalchemy
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import select

from app.models import BannedIP
from app.services.abuse import ban_ip
from app.services.abuse_store_pg import PgAbuseStore
from tests.conftest import TEST_DB_URL

pytestmark = pytest.mark.pg_only


@pytest.fixture
async def stores(_pg_schema):
    engines = [create_async_engine(TEST_DB_URL, poolclass=NullPool) for _ in range(2)]
    async with engines[0].begin() as c:
        await c.execute(sqlalchemy.text(
            "TRUNCATE auth_fail_events, auth_blocks, rate_counters, banned_ip"))
    yield [PgAbuseStore(e) for e in engines]
    for e in engines:
        await e.dispose()


async def test_failures_add_up_across_stores_and_lock_trips(stores):
    a, b = stores
    for _ in range(3):
        assert await a.record_fail("Bob", "1.1.1.1", 5, 900) is False
    assert await b.record_fail("bob", "1.1.1.1", 5, 900) is False
    assert await b.record_fail("BOB", "1.1.1.1", 5, 900) is True       # 3 on A + 2 on B
    assert await a.is_locked("bob", "1.1.1.1")
    assert 0 < await a.locked_for("bob") <= 900


async def test_clear_user_on_a_unlocks_on_b(stores):
    a, b = stores
    for _ in range(2):
        await a.record_fail("bob", "1.1.1.1", 2, 900)
    assert await b.is_locked("bob", "1.1.1.1")
    await a.clear_user("bob")
    assert not await b.is_locked("bob", "1.1.1.1")
    assert await b.locked_for("bob") == 0


async def test_clear_unlocks_pair(stores):
    a, b = stores
    for _ in range(2):
        await a.record_fail("bob", "1.1.1.1", 2, 900)
    await b.clear("bob", "1.1.1.1")
    assert not await a.is_locked("bob", "1.1.1.1")


async def test_ipv6_same_64_shares_key(stores):
    a, b = stores
    await a.record_fail("bob", "2001:db8::1", 2, 900)
    assert await b.record_fail("bob", "2001:db8::ffff", 2, 900) is True
    assert await b.is_locked("bob", "2001:db8:0:0:1::5")


async def test_window_uses_db_time_not_app_clock(stores, monkeypatch):
    a, b = stores
    await a.record_fail("bob", "1.1.1.1", 2, 900)
    monkeypatch.setattr(time, "time", lambda: 4_000_000_000.0)
    monkeypatch.setattr(time, "monotonic", lambda: 4_000_000_000.0)
    assert await b.record_fail("bob", "1.1.1.1", 2, 900) is True       # still in DB window


async def test_brake_lets_exactly_one_through(stores):
    a, b = stores
    for _ in range(3):
        await a.record_fail("bob", f"9.9.9.{_}", 99, 900)
    results = await asyncio.gather(
        *[(a if i % 2 else b).throttled("bob", 3, 900) for i in range(20)])
    assert results.count(False) == 1
    assert results.count(True) == 19


async def test_brake_below_threshold_never_throttles(stores):
    assert await stores[0].throttled("bob", 3, 900) is False


async def test_device_block_shared_and_cleared(stores):
    a, b = stores
    await a.device_fail("rnd", 2, 900)
    assert not await b.device_blocked("rnd")
    await b.device_fail("rnd", 2, 900)
    assert await a.device_blocked("rnd")
    await a.device_clear("rnd")
    assert not await b.device_blocked("rnd")


async def test_ip_fail_fires_once_and_ban_upsert_leaves_one_row(stores, session):
    a, b = stores
    fired = [await a.ip_fail("5.5.5.5", 3, 60), await b.ip_fail("5.5.5.5", 3, 60)]
    fired.append(await a.ip_fail("5.5.5.5", 3, 60))
    assert fired == [False, False, True]
    assert await b.ip_fail("5.5.5.5", 3, 60) is False                 # window cleared
    await ban_ip(session, "5.5.5.5", "x", 60)
    await ban_ip(session, "5.5.5.5", "x", 60)
    await session.flush()
    assert len((await session.exec(select(BannedIP))).all()) == 1


async def test_rate_limit_shared_across_stores(stores):
    a, b = stores
    limit = 6
    got = [await (a if i % 2 else b).rate_allow("ip:x", limit, 3600) for i in range(limit)]
    assert all(got)
    assert await a.rate_allow("ip:x", limit, 3600) is False
    assert await b.rate_allow("ip:y", limit, 3600) is True             # other key unaffected


async def test_db_error_propagates_for_caller_fail_policy(_pg_schema):
    eng = create_async_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x", poolclass=NullPool)
    s = PgAbuseStore(eng)
    for call in (s.is_locked("u", "1.1.1.1"), s.throttled("u", 3, 60),
                 s.ip_fail("1.1.1.1", 3, 60), s.rate_allow("k", 3, 60)):
        with pytest.raises(Exception):
            await call


async def test_fail_policy_with_pg_store_down(_pg_schema, monkeypatch):
    from app.services import abuse_store, login_flow
    eng = create_async_engine("postgresql+asyncpg://x:x@127.0.0.1:1/x", poolclass=NullPool)
    monkeypatch.setattr(abuse_store, "get_abuse_store", lambda: PgAbuseStore(eng))
    assert await login_flow.blocked("u", "1.2.3.4", None) is True
    assert await login_flow.locked("u", "1.2.3.4", None) is True
