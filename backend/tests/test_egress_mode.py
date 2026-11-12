import pytest

from app.models import Group, User, UserGroup
from app.services.egress_mode import resolve_egress_mode


@pytest.mark.asyncio
async def test_default_is_category(admin_client):
    r = await admin_client.post("/api/groups", json={"name": "a"})
    assert r.status_code == 201
    assert r.json()["egress_mode"] == "category"
    assert (await admin_client.get("/api/groups")).json()[0]["egress_mode"] == "category"


@pytest.mark.asyncio
async def test_create_update_and_validation(admin_client):
    r = await admin_client.post("/api/groups", json={"name": "a", "egress_mode": "allowlist"})
    assert r.status_code == 201 and r.json()["egress_mode"] == "allowlist"
    gid = r.json()["id"]
    r = await admin_client.patch(f"/api/groups/{gid}", json={"egress_mode": "category"})
    assert r.status_code == 200 and r.json()["egress_mode"] == "category"
    assert (await admin_client.patch(f"/api/groups/{gid}", json={"egress_mode": "open"})).status_code == 422
    assert (await admin_client.post("/api/groups", json={"name": "b", "egress_mode": "x"})).status_code == 422


@pytest.mark.asyncio
async def test_strictest_wins(session):
    u = User(username="eg", password_hash="x", role="member")
    session.add(u)
    g1, g2 = Group(name="g1"), Group(name="g2", egress_mode="allowlist")
    session.add_all([g1, g2])
    await session.commit()
    assert await resolve_egress_mode(session, u) == "category"  # no group
    session.add(UserGroup(user_id=u.id, group_id=g1.id))
    await session.commit()
    assert await resolve_egress_mode(session, u) == "category"
    session.add(UserGroup(user_id=u.id, group_id=g2.id))
    await session.commit()
    assert await resolve_egress_mode(session, u) == "allowlist"
