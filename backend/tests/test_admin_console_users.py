"""Admin console user detail API (styx-portal#302)."""
from datetime import datetime

import pytest
from sqlmodel import select

from app.models import Group, Instance, ServiceTemplate, User, UserGroup

URL = "/api/admin/console/users/{}"
KEYS = {"id", "username", "display_name", "email", "staff_role", "groups",
        "created_at", "last_login", "storage", "sessions"}


async def _member(session) -> User:
    return (await session.exec(select(User).where(User.username == "member"))).one()


async def _set_role(session, staff_role: str) -> User:
    user = await _member(session)
    user.staff_role = staff_role
    user.email = "m@example.test"
    user.last_login = datetime(2026, 11, 12, 9, 0)
    session.add(user)
    await session.commit()
    return user


@pytest.mark.parametrize("role", ["platform-admin", "help-desk", "auditor"])
async def test_allowed_roles_get_detail(member_client, session, role):
    user = await _set_role(session, role)
    grp = Group(name="eng")
    tpl = ServiceTemplate(name="desk", display_name="Desk", image="img/desk:1")
    session.add_all([grp, tpl])
    await session.commit()
    session.add(UserGroup(user_id=user.id, group_id=grp.id))
    session.add(Instance(template_id=tpl.id, owner_id=user.id, name="a", subdomain="a",
                         status="running"))
    session.add(Instance(template_id=tpl.id, owner_id=user.id, name="b", subdomain="b",
                         status="stopped"))
    await session.commit()
    r = await member_client.get(URL.format(user.id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == KEYS  # no hash/token/secret keys
    assert body["username"] == "member" and body["email"] == "m@example.test"
    assert body["staff_role"] == role and body["groups"] == ["eng"]
    assert body["last_login"].startswith("2026-11-12T09:00")
    assert [s["template"] for s in body["sessions"]] == ["desk"]
    assert set(body["storage"]) == {"used_bytes", "quota_bytes", "percent", "warn"}


@pytest.mark.parametrize("role", ["", "group-manager"])
async def test_other_roles_forbidden(member_client, session, role):
    user = await _set_role(session, role)
    assert (await member_client.get(URL.format(user.id))).status_code == 403


async def test_unknown_id_404(admin_client):
    assert (await admin_client.get(URL.format("nope"))).status_code == 404


async def test_storage_reuses_me_logic(member_client, session, monkeypatch):
    user = await _set_role(session, "help-desk")

    async def fake(_session, uid):
        assert uid == user.id
        return {"used_bytes": 9, "quota_bytes": 10, "percent": 90.0, "warn": True}
    monkeypatch.setattr("app.routers.admin_console.user_storage", fake)
    body = (await member_client.get(URL.format(user.id))).json()
    assert body["storage"]["warn"] is True and body["storage"]["used_bytes"] == 9
