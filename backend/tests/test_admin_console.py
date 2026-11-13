"""Admin console: staff-role gate + sessions/capacity API (styx-portal#298)."""
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.models import Instance, ServiceTemplate, User
from app.security.deps import require_staff_role

PATHS = ["sessions", "capacity"]


async def _set_role(session, staff_role: str) -> None:
    user = (await session.exec(select(User).where(User.username == "member"))).one()
    user.staff_role = staff_role
    session.add(user)
    await session.commit()


async def _seed(session) -> None:
    owner = (await session.exec(select(User).where(User.username == "member"))).one()
    tpl = ServiceTemplate(name="desk", display_name="Desk", image="img/desk:1")
    session.add(tpl)
    await session.commit()
    started = datetime(2026, 11, 13, 8, 0, tzinfo=timezone.utc).replace(tzinfo=None)
    session.add(Instance(template_id=tpl.id, owner_id=owner.id, name="a", subdomain="a",
                         status="running", started_at=started))
    session.add(Instance(template_id=tpl.id, owner_id=owner.id, name="b", subdomain="b",
                         status="stopped"))
    await session.commit()


@pytest.mark.parametrize("role", ["platform-admin", "help-desk", "auditor"])
@pytest.mark.parametrize("path", PATHS)
async def test_staff_roles_allowed(member_client, session, role, path):
    await _set_role(session, role)
    r = await member_client.get(f"/api/admin/console/{path}")
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("role", ["", "group-manager"])
@pytest.mark.parametrize("path", PATHS)
async def test_other_roles_forbidden(member_client, session, role, path):
    await _set_role(session, role)
    assert (await member_client.get(f"/api/admin/console/{path}")).status_code == 403


@pytest.mark.parametrize("path", PATHS)
async def test_admin_counts_as_platform_admin(admin_client, path):
    assert (await admin_client.get(f"/api/admin/console/{path}")).status_code == 200


async def test_sessions_lists_running_only(member_client, session):
    await _set_role(session, "auditor")
    await _seed(session)
    rows = (await member_client.get("/api/admin/console/sessions")).json()["sessions"]
    assert len(rows) == 1
    row = rows[0]
    assert row["owner"] == "member" and row["template"] == "desk"
    assert row["image"] == "img/desk:1" and row["started_at"].startswith("2026-11-13T08:00")
    assert set(row) == {"id", "owner", "template", "image", "started_at", "node"}


async def test_capacity_counts(member_client, session):
    await _set_role(session, "help-desk")
    await _seed(session)
    j = (await member_client.get("/api/admin/console/capacity")).json()
    assert j["running"] == 1
    assert {"max_per_user", "limit", "live_streams", "per_node"} <= set(j)
    assert sum(j["per_node"].values()) == 1


async def test_require_staff_role_unit():
    dep = require_staff_role("auditor")
    assert await dep(User(username="x", role="member", staff_role="auditor")) is not None
    assert await require_staff_role("platform-admin")(User(username="y", role="admin"))
    with pytest.raises(HTTPException) as e:
        await dep(User(username="z", role="member", staff_role="help-desk"))
    assert e.value.status_code == 403


async def test_require_staff_role_admin_needs_platform_admin_in_roles():
    with pytest.raises(HTTPException):
        await require_staff_role("auditor")(User(username="y", role="admin"))
