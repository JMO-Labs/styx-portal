"""run_deletion_pass(): 90-day account + home deletion (#126, ADR-0022)."""
import asyncio

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlmodel import select

from app.models import (AuditLog, FederatedIdentity, ServiceTemplate, User,
                        UserProfile)
from app.services.account_deletion import run_deletion_pass

NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


class NotFound(Exception):
    status_code = 404


async def _seed(session, name, age_days, enabled=False):
    u = User(username=name, password_hash="x", is_active=enabled,
             disabled_at=None if age_days is None else NOW - timedelta(days=age_days))
    session.add(u)
    t = ServiceTemplate(name=f"t{name}", display_name="T", image="img")
    session.add(t)
    await session.commit()
    session.add(UserProfile(user_id=u.id, template_id=t.id, volume_name=f"home-{name}"))
    session.add(FederatedIdentity(user_id=u.id, provider="kc", subject=f"kc-{name}"))
    await session.commit()
    return u


def _deps():
    return MagicMock(), AsyncMock()


async def test_deletes_expired_user_volume_keycloak_and_audits(session):
    u = await _seed(session, "old", 91)
    uid = u.id
    rt, kc = _deps()
    n = await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc)
    assert n == 1
    rt.remove_volume.assert_called_once_with("home-old")
    kc.assert_awaited_once_with("kc-old")
    session.expire_all()
    assert await session.get(User, uid) is None
    ev = (await session.exec(select(AuditLog).where(AuditLog.action == "account.deleted"))).all()
    assert len(ev) == 1 and ev[0].resource == uid
    assert ev[0].detail == {"username": "old", "user_id": uid}


async def test_boundary_90_days_deleted(session):
    await _seed(session, "edge", 90)
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 1


async def test_recent_and_reenabled_untouched(session):
    await _seed(session, "recent", 89)
    await _seed(session, "never", None, enabled=True)
    await _seed(session, "back", 100, enabled=True)  # re-enabled, stamp still set
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 0
    rt.remove_volume.assert_not_called()
    kc.assert_not_awaited()


async def test_idempotent_second_pass_noop(session):
    await _seed(session, "old", 100)
    rt, kc = _deps()
    await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc)
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 0
    assert rt.remove_volume.call_count == 1
    assert kc.await_count == 1


async def test_404_counts_as_done(session):
    u = await _seed(session, "gone", 100)
    uid = u.id
    rt, kc = _deps()
    rt.remove_volume.side_effect = NotFound()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 1
    session.expire_all()
    assert await session.get(User, uid) is None


async def test_other_failure_keeps_user_for_retry(session):
    u = await _seed(session, "flaky", 100)
    uid = u.id
    rt, kc = _deps()
    kc.side_effect = RuntimeError("kc down")
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 0
    session.expire_all()
    assert await session.get(User, uid) is not None
    assert not (await session.exec(select(AuditLog).where(AuditLog.action == "account.deleted"))).all()


async def _as_user(client, session, user):
    from app.main import app
    from app.security.deps import get_current_user
    session.add(user)
    await session.commit()
    app.dependency_overrides[get_current_user] = lambda: user


@pytest.mark.parametrize("path", ["/api/instances", "/api/instances/x/start"])
async def test_disabled_user_gets_403(client, session, path):
    from app.main import app
    from app.security.deps import get_current_user
    u = User(username="dis", password_hash="x", is_active=False, disabled_at=NOW)
    await _as_user(client, session, u)
    try:
        r = await client.post(path, json={"template_id": "x", "name": "a", "subdomain": "a"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 403


def test_reenabled_is_not_disabled():
    from app.services.offboarding import is_disabled
    assert not is_disabled(User(username="b", password_hash="x", is_active=True, disabled_at=NOW))


async def test_loop_calls_pass_and_is_registered(monkeypatch):
    from contextlib import asynccontextmanager
    from pathlib import Path
    from app.services import account_deletion as ad
    calls = []

    async def fake_pass(s, now, **kw):
        calls.append(s)
        raise asyncio.CancelledError

    @asynccontextmanager
    async def sf():
        yield "sess"

    monkeypatch.setattr(ad, "run_deletion_pass", fake_pass)
    with pytest.raises(asyncio.CancelledError):
        await ad.account_deletion_loop(sf)
    assert calls == ["sess"]
    assert "account_deletion_loop, async_session" in (
        Path(__file__).parents[1] / "app/main.py").read_text()
