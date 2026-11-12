import pytest
from sqlmodel import select

from app.models import Group, User, UserGroup
from app.routers import auth as auth_mod
from app.services import federation


async def _user(session, name="kc"):
    u = User(username=name, email=f"{name}@x.io", password_hash="!", role="user")
    session.add(u)
    await session.commit()
    return u


async def _names(session, uid):
    rows = await session.exec(select(Group.name).join(UserGroup, UserGroup.group_id == Group.id)
                              .where(UserGroup.user_id == uid))
    return sorted(rows.all())


@pytest.mark.asyncio
async def test_sync_adds_creates_normalises_and_removes_stale(session):
    u = await _user(session)
    stale = Group(name="old", idp_managed=True)
    local = Group(name="local-only")
    session.add_all([stale, local])
    await session.commit()
    session.add_all([UserGroup(user_id=u.id, group_id=stale.id),
                     UserGroup(user_id=u.id, group_id=local.id)])
    await session.commit()

    await federation.sync_idp_groups(session, u, {"groups": ["/media", "/eng/ops", "bad,name"]})
    assert await _names(session, u.id) == ["eng/ops", "local-only", "media"]
    media = (await session.exec(select(Group).where(Group.name == "media"))).one()
    assert media.idp_managed is True

    # second login: idempotent; claim drops media
    await federation.sync_idp_groups(session, u, {"groups": ["/eng/ops"]})
    assert await _names(session, u.id) == ["eng/ops", "local-only"]


@pytest.mark.asyncio
async def test_sync_leaves_existing_local_group_alone(session):
    u = await _user(session)
    session.add(Group(name="media"))
    await session.commit()
    await federation.sync_idp_groups(session, u, {"groups": ["/media"]})
    assert await _names(session, u.id) == []


@pytest.mark.asyncio
async def test_missing_claim_does_not_wipe(session):
    u = await _user(session)
    await federation.sync_idp_groups(session, u, {"groups": ["/a"]})
    await federation.sync_idp_groups(session, u, {})
    assert await _names(session, u.id) == ["a"]


@pytest.mark.asyncio
async def test_idp_group_membership_not_editable_via_api(admin_client, session):
    u = await _user(session)
    await federation.sync_idp_groups(session, u, {"groups": ["/a"]})
    ga = (await session.exec(select(Group).where(Group.name == "a"))).one()
    r = await admin_client.put(f"/api/users/{u.id}/groups", json={"group_ids": []})
    assert r.status_code == 409
    other = (await admin_client.post("/api/groups", json={"name": "loc"})).json()["id"]
    r = await admin_client.put(f"/api/users/{u.id}/groups", json={"group_ids": [ga.id, other]})
    assert r.status_code == 200  # IdP set unchanged, local add ok
    r = await admin_client.put(f"/api/users/{u.id}/groups", json={"group_ids": [other]})
    assert r.status_code == 409
    glob = Group(name="idp-x", idp_managed=True)
    session.add(glob)
    await session.commit()
    r = await admin_client.put(f"/api/users/{u.id}/groups", json={"group_ids": [ga.id, glob.id]})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_banner_url_exposed(client, monkeypatch):
    r = await client.get("/api/auth/setup-required")
    assert r.json()["banner_url"] == ""
    monkeypatch.setattr(auth_mod._settings, "BANNER_URL", "https://banner.example/")
    r = await client.get("/api/auth/setup-required")
    assert r.json()["banner_url"] == "https://banner.example/"
