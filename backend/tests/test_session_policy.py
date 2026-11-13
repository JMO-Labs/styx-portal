import pytest

from app.models import Group, User, UserGroup
from app.services.k8s_instance_objects import build_objects
from app.services.session_policy import (
    DEFAULT_IDLE_LOCK_S, effective_idle_lock_s, validate_idle_lock)


async def _user_with(session, *minutes):
    u = User(email="s@x.io", username="s", password_hash="x")
    session.add(u)
    groups = [Group(name=f"g{i}", idle_lock_minutes=m) for i, m in enumerate(minutes)]
    session.add_all(groups)
    await session.commit()
    session.add_all([UserGroup(user_id=u.id, group_id=g.id) for g in groups])
    await session.commit()
    return u


@pytest.mark.asyncio
async def test_no_groups_defaults_to_900(session):
    u = await _user_with(session)
    assert await effective_idle_lock_s(u, session) == DEFAULT_IDLE_LOCK_S == 900


@pytest.mark.asyncio
async def test_unset_groups_default(session):
    u = await _user_with(session, None, None)
    assert await effective_idle_lock_s(u, session) == 900


@pytest.mark.asyncio
async def test_min_of_groups_wins(session):
    u = await _user_with(session, 10, 5, None, 12)
    assert await effective_idle_lock_s(u, session) == 300


@pytest.mark.asyncio
async def test_enterprise_rejects_over_15_and_zero(admin_client, monkeypatch):
    monkeypatch.setenv("STYX_PROFILE", "enterprise")
    for bad in (16, 0):
        r = await admin_client.post("/api/groups", json={"name": f"b{bad}", "idle_lock_minutes": bad})
        assert r.status_code == 422, r.text
    r = await admin_client.post("/api/groups", json={"name": "ok", "idle_lock_minutes": 15})
    assert r.status_code == 201 and r.json()["idle_lock_minutes"] == 15
    r = await admin_client.patch(f"/api/groups/{r.json()['id']}", json={"idle_lock_minutes": 20})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_homelab_allows_over_15(admin_client, monkeypatch):
    monkeypatch.setenv("STYX_PROFILE", "homelab")
    r = await admin_client.post("/api/groups", json={"name": "long", "idle_lock_minutes": 60})
    assert r.status_code == 201


def test_validate_none_ok():
    validate_idle_lock(None)


def test_pod_env_values(monkeypatch):
    monkeypatch.setenv("DOMAIN", "example.com")
    dep, _ = build_objects(
        "selkies-abc", "selkies-desktop:latest",
        {"STYX_INSTANCE_ID": "inst-1", "STYX_LOCK_IDLE_S": "300"},
        {}, 3000, "ns", "u1")
    env = {e["name"]: e["value"]
           for e in dep["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["STYX_LOCK_IDLE_S"] == "300"
    assert env["STYX_INSTANCE_ID"] == "inst-1"
    assert env["STYX_UNLOCK_URL"] == "https://login.example.com/api/instances/inst-1/unlock"
