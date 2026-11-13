import pytest

from app.models import Group, User, UserGroup
from app.services.group_tier import resolve_group_tier


def test_no_groups_gives_empty_override():
    assert resolve_group_tier([]) == {}


def test_single_group_values_pass_through():
    g = Group(name="a", tier_cpu="6", tier_memory="8Gi", tier_fps=60,
              tier_resolution="2560x1440", tier_hidpi=True)
    assert resolve_group_tier([g]) == {
        "cpu": "6", "memory": "8Gi", "fps": 60, "resolution": "2560x1440", "hidpi": True}


def test_highest_cpu_memory_fps_win_across_groups():
    a = Group(name="a", tier_cpu="2", tier_memory="16Gi", tier_fps=30)
    b = Group(name="b", tier_cpu="8", tier_memory="4096Mi", tier_fps=60)
    c = Group(name="c")  # no overrides
    out = resolve_group_tier([a, b, c])
    assert out == {"cpu": "8", "memory": "16Gi", "fps": 60}


def test_memory_units_compared_by_size_not_text():
    a = Group(name="a", tier_memory="2048Mi")
    b = Group(name="b", tier_memory="1Gi")
    assert resolve_group_tier([a, b])["memory"] == "2048Mi"


@pytest.mark.asyncio
async def test_user_group_tier_loads_from_db(session):
    u = User(email="t@x.io", username="t", password_hash="x")
    g1 = Group(name="g1", tier_cpu="4", tier_fps=45)
    g2 = Group(name="g2", tier_cpu="2", tier_fps=60)
    session.add_all([u, g1, g2])
    await session.commit()
    session.add_all([UserGroup(user_id=u.id, group_id=g1.id),
                     UserGroup(user_id=u.id, group_id=g2.id)])
    await session.commit()
    from app.services.group_tier import user_group_tier
    assert await user_group_tier(session, u.id) == {"cpu": "4", "fps": 60}
    assert await user_group_tier(session, None) == {}


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {"tier_fps": 0}, {"tier_fps": -5}, {"tier_memory": "4Xi"}, {"tier_memory": "lots"},
    {"tier_cpu": "0"}, {"tier_cpu": "abc"}, {"tier_resolution": "big"},
])
async def test_api_rejects_invalid_tier(admin_client, body):
    gid = (await admin_client.post("/api/groups", json={"name": "t"})).json()["id"]
    r = await admin_client.patch(f"/api/groups/{gid}", json=body)
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_api_accepts_and_returns_tier(admin_client):
    gid = (await admin_client.post("/api/groups", json={"name": "t"})).json()["id"]
    body = {"tier_resolution": "2560x1440", "tier_fps": 60, "tier_hidpi": True,
            "tier_cpu": "6", "tier_memory": "8Gi"}
    r = await admin_client.patch(f"/api/groups/{gid}", json=body)
    assert r.status_code == 200, r.text
    assert {k: r.json()[k] for k in body} == body
    listed = [g for g in (await admin_client.get("/api/groups")).json() if g["id"] == gid][0]
    assert listed["tier_memory"] == "8Gi"
    # clearing back to null
    r = await admin_client.patch(f"/api/groups/{gid}", json={"tier_fps": None})
    assert r.json()["tier_fps"] is None


@pytest.mark.asyncio
async def test_api_create_with_tier(admin_client):
    r = await admin_client.post("/api/groups", json={"name": "c", "tier_cpu": "2"})
    assert r.status_code == 201 and r.json()["tier_cpu"] == "2"


def test_tier_env_maps_selkies_settings():
    from app.services.group_tier import tier_env
    assert tier_env({"resolution": "2560x1440", "fps": 60, "hidpi": True}) == {
        "SELKIES_MANUAL_WIDTH": "2560", "SELKIES_MANUAL_HEIGHT": "1440",
        "SELKIES_FRAMERATE": "60", "SELKIES_SCALING_DPI": "192"}
    assert tier_env({}) == {}


@pytest.mark.asyncio
async def test_launch_overrides_template_wins_and_k8s_only(session):
    from types import SimpleNamespace as NS
    from unittest.mock import MagicMock

    from app.services.group_tier import launch_overrides
    from app.services.k8s_instances import K8sInstanceRuntime

    u = User(email="l@x.io", username="l", password_hash="x")
    g = Group(name="lg", tier_cpu="6", tier_memory="8Gi", tier_fps=60)
    session.add_all([u, g])
    await session.commit()
    session.add(UserGroup(user_id=u.id, group_id=g.id))
    await session.commit()
    k8s = MagicMock(spec=K8sInstanceRuntime)
    inst = NS(owner_id=u.id, id="i1")

    env, mem, cpu = await launch_overrides(session, k8s, inst, NS(memory_limit=None, cpu_limit=None))
    assert (mem, cpu, env["SELKIES_FRAMERATE"]) == ("8Gi", "6", "60")
    env, mem, cpu = await launch_overrides(session, k8s, inst, NS(memory_limit="2g", cpu_limit="1"))
    assert (mem, cpu) == ("2g", "1")
    env, mem, cpu = await launch_overrides(session, MagicMock(), inst, NS(memory_limit=None, cpu_limit=None))
    assert (env, mem, cpu) == ({}, None, None)
