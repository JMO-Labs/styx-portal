"""System settings gated by staff role (styx-portal#309)."""
import pytest
from sqlmodel import select

from app.models import User

URL = "/api/system-settings"


async def _set_role(session, staff_role: str) -> None:
    user = (await session.exec(select(User).where(User.username == "member"))).one()
    user.staff_role = staff_role
    session.add(user)
    await session.commit()


@pytest.mark.parametrize("role", ["help-desk", "group-manager", ""])
async def test_non_platform_admin_cannot_patch(member_client, session, role):
    await _set_role(session, role)
    assert (await member_client.patch(URL, json={"LOCKOUT_THRESHOLD": 4})).status_code == 403
    assert (await member_client.post(f"{URL}/LOCKOUT_THRESHOLD/reset")).status_code == 403


async def test_auditor_reads_but_cannot_write(member_client, session):
    await _set_role(session, "auditor")
    assert (await member_client.get(URL)).status_code == 200
    assert (await member_client.patch(URL, json={"LOCKOUT_THRESHOLD": 4})).status_code == 403


async def test_help_desk_cannot_read(member_client, session):
    await _set_role(session, "help-desk")
    assert (await member_client.get(URL)).status_code == 403


async def test_platform_admin_staff_role_can_patch(member_client, session):
    await _set_role(session, "platform-admin")
    assert (await member_client.patch(URL, json={"LOCKOUT_THRESHOLD": 4})).status_code == 200
