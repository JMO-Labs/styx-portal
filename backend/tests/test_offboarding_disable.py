"""disable_account(): lifecycle fields, session kill, idempotency, audit (#115)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import select
from starlette.requests import Request

from app.models import AuditLog, Instance, PosixUid, RefreshToken, ServiceTemplate, User
from app.security import tokens
from app.security.deps import get_current_user
from app.services.offboarding import disable_account


async def _user(session, name="bob"):
    u = User(username=name, password_hash="x")
    session.add(u)
    await session.commit()
    return u


async def _instances(session, user, statuses):
    t = ServiceTemplate(name="t", display_name="T", image="img")
    session.add(t)
    await session.commit()
    out = []
    for i, st in enumerate(statuses):
        inst = Instance(template_id=t.id, owner_id=user.id, name=f"i{i}",
                        subdomain=f"s{user.username}{i}", status=st, container_id=f"c{i}")
        session.add(inst)
        out.append(inst)
    await session.commit()
    return out


def _req(token):
    return Request({"type": "http", "method": "GET", "path": "/api/x", "query_string": b"",
                    "headers": [(b"cookie", f"access_token={token}".encode())]})


async def test_lifecycle_fields_default_none(session):
    u = await _user(session)
    assert (u.end_date, u.disabled_at, u.disabled_reason, u.reviewed_at) == (None,) * 4


async def test_disable_sets_fields_and_rejects_old_token(session):
    u = await _user(session)
    old = tokens.create_access_token(u.id, u.role, tv=u.token_version)
    await get_current_user(_req(old), session)  # valid before
    rt = RefreshToken(jti="j1", user_id=u.id, family_id="f",
                      expires_at=datetime.now(timezone.utc) + timedelta(days=1))
    session.add(rt)
    await session.commit()
    await disable_account(session, u, "end_date", "admin-id", runtime=MagicMock())
    assert u.is_active is False and u.disabled_reason == "end_date"
    assert u.disabled_at is not None and u.token_version == 1
    with pytest.raises(HTTPException) as e:
        await get_current_user(_req(old), session)
    assert e.value.status_code == 401
    await session.refresh(rt)
    assert rt.revoked is True


async def test_stops_live_instances_only(session):
    u = await _user(session)
    insts = await _instances(session, u, ["running", "idle", "stopped"])
    rt = MagicMock()
    await disable_account(session, u, "inactivity", "sys", runtime=rt)
    stopped = {c.args[0] for c in rt.stop_container.call_args_list}
    assert stopped == {"c0", "c1"}
    for i in insts:
        await session.refresh(i)
    assert [i.status for i in insts] == ["stopped"] * 3
    assert insts[0].stopped_at is not None


async def test_idempotent_and_single_audit(session):
    u = await _user(session)
    rt = MagicMock()
    assert await disable_account(session, u, "r1", "a", runtime=rt) is True
    assert await disable_account(session, u, "r2", "a", runtime=rt) is False
    assert u.disabled_reason == "r1" and u.token_version == 1
    rows = (await session.exec(select(AuditLog).where(
        AuditLog.action == "account.disabled"))).all()
    assert len(rows) == 1
    assert rows[0].resource == u.id and rows[0].detail["reason"] == "r1"


async def test_session_dead_in_same_call(session):
    """Token rejected and instances stopped before the call returns (<< 60 s)."""
    u = await _user(session)
    await _instances(session, u, ["running"])
    tok = tokens.create_access_token(u.id, u.role, tv=u.token_version)
    rt = MagicMock()
    await disable_account(session, u, "remove_access", "a", runtime=rt)
    rt.stop_container.assert_called_once_with("c0")
    with pytest.raises(HTTPException):
        await get_current_user(_req(tok), session)


async def test_default_runtime_resolved_when_none(session, monkeypatch):
    u = await _user(session)
    await _instances(session, u, ["running"])
    rt = MagicMock()
    monkeypatch.setattr("app.services.k8s_runtime.instance_runtime", lambda: rt)
    await disable_account(session, u, "r", "a")
    rt.stop_container.assert_called_once_with("c0")


async def test_stop_failure_still_disables_and_marks_stopped(session, caplog):
    u = await _user(session)
    insts = await _instances(session, u, ["running", "idle"])
    rt = MagicMock()
    rt.stop_container.side_effect = [RuntimeError("boom"), None]
    assert await disable_account(session, u, "r", "a", runtime=rt) is True
    assert u.disabled_at is not None and rt.stop_container.call_count == 2
    for i in insts:
        await session.refresh(i)
    assert [i.status for i in insts] == ["stopped"] * 2
    assert "offboarding: stop failed" in caplog.text


async def _k8s_user(session, monkeypatch, uid=2001):
    monkeypatch.setenv("ROUTE_BACKEND", "k8s")
    u = await _user(session)
    if uid is not None:
        session.add(PosixUid(uid=uid, user_key=u.id))
        await session.commit()
    return u


async def test_freeze_home_resolves_default_runtime(session, monkeypatch):
    u = await _k8s_user(session, monkeypatch)
    rt = MagicMock()
    monkeypatch.setattr("app.services.k8s_runtime.instance_runtime", lambda: rt)
    await disable_account(session, u, "r", "a")
    assert rt._c.patch_merge.call_args.args[3] == "home-2001"


async def test_freeze_home_skipped_without_posix_uid(session, monkeypatch):
    u = await _k8s_user(session, monkeypatch, uid=None)
    rt = MagicMock()
    await disable_account(session, u, "r", "a", runtime=rt)
    rt._c.patch_merge.assert_not_called()


async def test_freeze_home_failure_still_disables(session, monkeypatch, caplog):
    u = await _k8s_user(session, monkeypatch)
    rt = MagicMock()
    rt._c.patch_merge.side_effect = RuntimeError("boom")
    assert await disable_account(session, u, "r", "a", runtime=rt) is True
    assert u.disabled_at is not None
    assert "offboarding: home freeze failed" in caplog.text
