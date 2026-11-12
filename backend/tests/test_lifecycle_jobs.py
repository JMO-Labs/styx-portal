"""Leader-only end-date / inactivity disable job (#125, ADR-0022)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from app.config import Settings
from app.models import AuditLog, FederatedIdentity, User
from app.services import lifecycle_jobs
from app.services.lifecycle_jobs import lifecycle_tick, run_lifecycle_pass

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


async def _u(session, name, **kw):
    u = User(username=name, password_hash="x", **kw)
    session.add(u)
    await session.commit()
    return u


async def _events(session):
    return len((await session.exec(select(AuditLog).where(
        AuditLog.action == "account.disabled"))).all())


@pytest.fixture
def kc(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr(lifecycle_jobs.kc_admin, "disable_user", m)
    return m


async def test_end_date_disables(session, kc):
    u = await _u(session, "a", end_date=NOW - timedelta(minutes=1), last_login=NOW)
    keep = await _u(session, "b", end_date=NOW + timedelta(days=1), last_login=NOW)
    assert await run_lifecycle_pass(session, NOW) == 1
    await session.refresh(u)
    await session.refresh(keep)
    assert not u.is_active and u.disabled_reason == "end_date"
    assert keep.is_active


async def test_inactivity_disables_by_last_login_or_created(session, kc):
    old = await _u(session, "old", last_login=NOW - timedelta(days=36))
    never = await _u(session, "never", created_at=NOW - timedelta(days=40))
    fresh = await _u(session, "fresh", last_login=NOW - timedelta(days=34))
    newbie = await _u(session, "newbie", created_at=NOW - timedelta(days=1))
    assert await run_lifecycle_pass(session, NOW) == 2
    for u in (old, never, fresh, newbie):
        await session.refresh(u)
    assert old.disabled_reason == never.disabled_reason == "inactivity"
    assert fresh.is_active and newbie.is_active


async def test_admin_skipped_for_inactivity(session, kc):
    adm = await _u(session, "root", role="admin", last_login=NOW - timedelta(days=90))
    assert await run_lifecycle_pass(session, NOW) == 0
    await session.refresh(adm)
    assert adm.is_active


async def test_idempotent_no_extra_audit(session, kc):
    await _u(session, "a", end_date=NOW - timedelta(days=1))
    await _u(session, "b", last_login=NOW - timedelta(days=50))
    assert await run_lifecycle_pass(session, NOW) == 2
    assert await _events(session) == 2
    assert await run_lifecycle_pass(session, NOW) == 0
    assert await _events(session) == 2


async def test_calls_kc_disable_for_federated_subjects(session, kc):
    u = await _u(session, "a", end_date=NOW - timedelta(days=1))
    session.add(FederatedIdentity(user_id=u.id, provider="keycloak", subject="kc-1"))
    await session.commit()
    await run_lifecycle_pass(session, NOW)
    kc.assert_awaited_once_with("kc-1")


async def test_kc_failure_does_not_block(session, kc):
    kc.side_effect = RuntimeError("down")
    u = await _u(session, "a", end_date=NOW - timedelta(days=1))
    session.add(FederatedIdentity(user_id=u.id, provider="keycloak", subject="kc-1"))
    await session.commit()
    assert await run_lifecycle_pass(session, NOW) == 1


async def test_inactivity_days_configurable(session, kc):
    assert Settings().LIFECYCLE_INACTIVITY_DAYS == 35
    await _u(session, "a", last_login=NOW - timedelta(days=10))
    assert await run_lifecycle_pass(session, NOW, inactivity_days=7) == 1


async def test_non_leader_tick_does_nothing(session, kc):
    await _u(session, "a", end_date=NOW - timedelta(days=1))
    assert await lifecycle_tick(session, NOW, is_leader=lambda: False) == 0
    assert await lifecycle_tick(session, NOW, is_leader=lambda: True) == 1


async def test_already_disabled_race_is_skipped(session, kc, monkeypatch):
    await _u(session, "a", end_date=NOW - timedelta(days=1), last_login=NOW)
    monkeypatch.setattr(lifecycle_jobs, "disable_account", AsyncMock(return_value=False))
    assert await run_lifecycle_pass(session, NOW) == 0
    kc.assert_not_awaited()
