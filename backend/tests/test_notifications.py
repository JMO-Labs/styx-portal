# backend/tests/test_notifications.py
import pytest
from sqlmodel import select

from app.models import Notification, User
from app.services.notifications import notify


async def _uid(session, name):
    return (await session.exec(select(User).where(User.username == name))).first().id


@pytest.mark.asyncio
async def test_list_and_read(member_client, session):
    uid = await _uid(session, "member")
    for i in range(3):
        await notify(session, uid, f"t{i}", "b", link="/x" if i == 0 else None)
    r = await member_client.get("/api/me/notifications")
    assert r.status_code == 200
    data = r.json()
    assert data["unread"] == 3 and len(data["items"]) == 3
    nid = data["items"][0]["id"]
    assert (await member_client.post(f"/api/me/notifications/{nid}/read")).status_code == 200
    assert (await member_client.get("/api/me/notifications")).json()["unread"] == 2
    assert (await member_client.post("/api/me/notifications/read-all")).status_code == 200
    assert (await member_client.get("/api/me/notifications")).json()["unread"] == 0


@pytest.mark.asyncio
async def test_list_capped_at_50(member_client, session):
    uid = await _uid(session, "member")
    for i in range(55):
        await notify(session, uid, f"t{i}", "b")
    data = (await member_client.get("/api/me/notifications")).json()
    assert len(data["items"]) == 50 and data["unread"] == 55


@pytest.mark.asyncio
async def test_cross_user_read_404(member_client, session):
    other = User(username="other", password_hash="x", role="member", is_active=True)
    session.add(other)
    await session.commit()
    n = await notify(session, other.id, "secret", "b")
    r = await member_client.post(f"/api/me/notifications/{n.id}/read")
    assert r.status_code == 404
    assert (await session.get(Notification, n.id)).read_at is None


@pytest.mark.asyncio
async def test_admin_send_one_and_broadcast(admin_client, session):
    uid = (await session.exec(select(User))).first().id
    r = await admin_client.post("/api/admin/notifications",
                                json={"user_id": uid, "title": "hi", "body": "b"})
    assert r.status_code == 201 and r.json()["created"] == 1
    session.add(User(username="u2", password_hash="x", role="member", is_active=True))
    await session.commit()
    r = await admin_client.post("/api/admin/notifications",
                                json={"all": True, "title": "all", "body": "b"})
    assert r.json()["created"] == 2
    r = await admin_client.post("/api/admin/notifications", json={"title": "t", "body": "b"})
    assert r.status_code == 422
    r = await admin_client.post("/api/admin/notifications",
                                json={"user_id": "nope", "title": "t", "body": "b"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_non_admin_403(member_client):
    r = await member_client.post("/api/admin/notifications",
                                 json={"all": True, "title": "t", "body": "b"})
    assert r.status_code == 403
