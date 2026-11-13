import pytest
from sqlmodel import select

from app.models import AuditLog, Instance, ServiceTemplate, SessionTakeover, User


@pytest.fixture
async def inst(session):
    t = ServiceTemplate(name="t", display_name="T", image="img")
    session.add(t)
    await session.commit()
    o = User(username="owner", password_hash="x", role="member", is_active=True)
    session.add(o)
    await session.commit()
    i = Instance(id="i-1", template_id=t.id, name="n", subdomain="s1", owner_id=o.id)
    session.add(i)
    await session.commit()
    return i


async def _actions(session):
    return [a.action for a in (await session.exec(select(AuditLog).order_by(AuditLog.ts))).all()]


async def _set_staff(session, staff):
    u = (await session.exec(select(User).where(User.username == "member"))).one()
    u.staff_role = staff
    session.add(u)
    await session.commit()


async def test_start_allowed_admin(admin_client, inst, session):
    r = await admin_client.post("/api/instances/i-1/takeover",
                                json={"mode": "view", "reason": " ticket 42 "})
    assert r.status_code == 201, r.text
    row = (await session.exec(select(SessionTakeover))).one()
    assert (row.instance_id, row.mode, row.reason, row.ended_at) == ("i-1", "view", "ticket 42", None)
    assert row.actor_id and "takeover.start" in await _actions(session)
    a = (await session.exec(select(AuditLog).where(AuditLog.action == "takeover.start"))).one()
    assert a.detail["mode"] == "view" and a.detail["reason"] == "ticket 42"
    assert "started_at" in a.detail and a.detail["actor_id"] == row.actor_id
    assert row.user_id == inst.owner_id and a.detail["user_id"] == inst.owner_id


async def test_start_allowed_help_desk(member_client, inst, session):
    await _set_staff(session, "help-desk")
    r = await member_client.post("/api/instances/i-1/takeover",
                                 json={"mode": "control", "reason": "fix"})
    assert r.status_code == 201


@pytest.mark.parametrize("staff", ["auditor", "group-manager", ""])
async def test_start_denied(member_client, inst, session, staff):
    await _set_staff(session, staff)
    r = await member_client.post("/api/instances/i-1/takeover",
                                 json={"mode": "view", "reason": "x"})
    assert r.status_code == 403
    assert (await session.exec(select(SessionTakeover))).first() is None
    assert [a for a in await _actions(session) if a != "auth.login"] == ["takeover.denied"]


@pytest.mark.parametrize("reason", ["", "   ", "\n\t"])
async def test_reason_required(admin_client, inst, reason):
    r = await admin_client.post("/api/instances/i-1/takeover",
                                json={"mode": "view", "reason": reason})
    assert r.status_code == 422


async def test_bad_mode(admin_client, inst):
    r = await admin_client.post("/api/instances/i-1/takeover",
                                json={"mode": "edit", "reason": "x"})
    assert r.status_code == 422


async def test_conflict(admin_client, inst):
    body = {"mode": "view", "reason": "x"}
    assert (await admin_client.post("/api/instances/i-1/takeover", json=body)).status_code == 201
    assert (await admin_client.post("/api/instances/i-1/takeover", json=body)).status_code == 409


async def test_unknown_instance(admin_client):
    r = await admin_client.post("/api/instances/nope/takeover",
                                json={"mode": "view", "reason": "x"})
    assert r.status_code == 404


async def test_end(admin_client, inst, session):
    await admin_client.post("/api/instances/i-1/takeover", json={"mode": "control", "reason": "r"})
    r = await admin_client.delete("/api/instances/i-1/takeover")
    assert r.status_code == 204
    row = (await session.exec(select(SessionTakeover))).one()
    assert row.ended_at is not None
    a = (await session.exec(select(AuditLog).where(AuditLog.action == "takeover.end"))).one()
    assert a.detail["reason"] == "r" and a.detail["mode"] == "control"
    assert a.detail["started_at"] and a.detail["ended_at"]
    # a new takeover is allowed after end
    r = await admin_client.post("/api/instances/i-1/takeover", json={"mode": "view", "reason": "again"})
    assert r.status_code == 201


async def test_end_without_active(admin_client, inst):
    assert (await admin_client.delete("/api/instances/i-1/takeover")).status_code == 404


async def test_end_denied(member_client, inst, session):
    await _set_staff(session, "auditor")
    assert (await member_client.delete("/api/instances/i-1/takeover")).status_code == 403
    assert "takeover.denied" in await _actions(session)


async def test_instance_delete_keeps_takeover_record(admin_client, inst, session):
    await admin_client.post("/api/instances/i-1/takeover", json={"mode": "view", "reason": "r"})
    assert (await admin_client.delete("/api/instances/i-1/takeover")).status_code == 204
    assert (await admin_client.delete("/api/instances/i-1")).status_code == 204
    row = (await session.exec(select(SessionTakeover))).one()
    assert row.instance_id == "i-1" and row.user_id == inst.owner_id


def test_takeover_has_no_instance_fk():
    assert not SessionTakeover.__table__.c.instance_id.foreign_keys
