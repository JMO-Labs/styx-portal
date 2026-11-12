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
    session.add(FederatedIdentity(user_id=u.id, provider="keycloak", subject=f"kc-{name}"))
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


async def test_only_keycloak_identities_sent_to_kc(session):
    u = await _seed(session, "mixed", 100)
    session.add(FederatedIdentity(user_id=u.id, provider="github", subject="gh-1"))
    await session.commit()
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 1
    kc.assert_awaited_once_with("kc-mixed")


async def test_user_fk_rows_cleaned_with_fks_enforced(session):
    from sqlalchemy import text
    from app.models import (Group, Invite, TurnUsage, UserGroup, Workstation,
                            WorkstationAccess, WorkstationEnrollmentToken)
    if session.bind.dialect.name == "sqlite":
        await session.exec(text("PRAGMA foreign_keys=ON"))
    admin = User(username="adm", password_hash="x", role="admin")
    session.add(admin)
    await session.commit()
    u = await _seed(session, "member", 100)
    uid = u.id
    g = Group(name="g1")
    ws = Workstation(name="w", subdomain="w1", created_by=uid, occupied_by=uid)
    session.add_all([g, ws])
    await session.commit()
    own = ServiceTemplate(name="mine", display_name="M", image="i", owner_id=uid)
    session.add_all([
        UserGroup(user_id=uid, group_id=g.id),
        WorkstationAccess(workstation_id=ws.id, user_id=uid),
        TurnUsage(month="2026-11", workstation_id=ws.id, user_id=uid, bytes=1),
        Invite(token_hash="h", created_by=uid),
        WorkstationEnrollmentToken(token_hash="e", created_by=uid, expires_at=NOW),
        own,
    ])
    await session.commit()
    aid, wid, tid = admin.id, ws.id, own.id
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 1
    session.expire_all()
    assert await session.get(User, uid) is None
    assert not (await session.exec(select(UserGroup))).all()
    assert not (await session.exec(select(WorkstationAccess))).all()
    assert (await session.exec(select(TurnUsage))).one().user_id is None
    ws2 = await session.get(Workstation, wid)
    assert ws2.occupied_by is None and ws2.created_by == aid
    assert (await session.exec(select(Invite))).one().created_by == aid
    assert (await session.exec(select(WorkstationEnrollmentToken))).one().created_by == aid
    # private template stays private (NULL owner would make it global)
    assert (await session.get(ServiceTemplate, tid)).owner_id == aid


async def test_loop_forwards_configured_retention(monkeypatch):
    from contextlib import asynccontextmanager
    from app.services import account_deletion as ad
    seen = {}

    async def fake_pass(s, now, **kw):
        seen.update(kw)
        raise asyncio.CancelledError

    @asynccontextmanager
    async def sf():
        yield "sess"

    monkeypatch.setattr(ad, "run_deletion_pass", fake_pass)
    monkeypatch.setenv("ACCOUNT_DELETION_RETENTION_DAYS", "30")
    with pytest.raises(asyncio.CancelledError):
        await ad.account_deletion_loop(sf)
    assert seen["retention_days"] == 30


async def test_no_admin_to_take_over_keeps_user(session):
    u = await _seed(session, "solo", 100)
    uid = u.id
    session.add(ServiceTemplate(name="priv", display_name="P", image="i", owner_id=uid))
    await session.commit()
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 0
    session.expire_all()
    assert await session.get(User, uid) is not None


async def test_volume_remove_failure_keeps_user(session):
    u = await _seed(session, "volfail", 100)
    uid = u.id
    rt, kc = _deps()
    rt.remove_volume.side_effect = RuntimeError("boom")
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 0
    kc.assert_not_awaited()
    session.expire_all()
    assert await session.get(User, uid) is not None


async def test_owned_instances_and_events_deleted(session):
    from app.models import Instance, SessionEvent
    u = await _seed(session, "owner", 100)
    uid = u.id
    tid = (await session.exec(select(UserProfile.template_id))).first()
    inst = Instance(template_id=tid, owner_id=uid, name="i", subdomain="i-owner")
    session.add(inst)
    await session.commit()
    session.add(SessionEvent(instance_id=inst.id, event_type="started"))
    await session.commit()
    rt, kc = _deps()
    assert await run_deletion_pass(session, NOW, runtime=rt, kc_delete=kc) == 1
    session.expire_all()
    assert not (await session.exec(select(Instance))).all()
    assert not (await session.exec(select(SessionEvent))).all()


async def test_default_runtime_from_instance_runtime(session, monkeypatch):
    from app.services import k8s_runtime
    rt = MagicMock()
    monkeypatch.setattr(k8s_runtime, "instance_runtime", lambda: rt)
    await _seed(session, "defrt", 100)
    assert await run_deletion_pass(session, NOW, kc_delete=AsyncMock()) == 1
    rt.remove_volume.assert_called_once_with("home-defrt")


def _loop_env(monkeypatch, ad, fake_pass):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def sf():
        yield "sess"

    async def stop(_):
        raise asyncio.CancelledError

    monkeypatch.setattr(ad, "run_deletion_pass", fake_pass)
    monkeypatch.setattr(ad.asyncio, "sleep", stop)
    return sf


async def test_loop_logs_when_accounts_deleted(monkeypatch, caplog):
    from app.services import account_deletion as ad

    async def fake_pass(s, now, **kw):
        return 2

    sf = _loop_env(monkeypatch, ad, fake_pass)
    with caplog.at_level("WARNING"), pytest.raises(asyncio.CancelledError):
        await ad.account_deletion_loop(sf)
    assert "deleted 2 expired disabled account(s)" in caplog.text


async def test_loop_survives_pass_failure(monkeypatch, caplog):
    from app.services import account_deletion as ad

    async def fake_pass(s, now, **kw):
        raise RuntimeError("db down")

    sf = _loop_env(monkeypatch, ad, fake_pass)
    with caplog.at_level("ERROR"), pytest.raises(asyncio.CancelledError):
        await ad.account_deletion_loop(sf)  # reaches sleep => exception was swallowed
    assert "account deletion pass failed" in caplog.text
