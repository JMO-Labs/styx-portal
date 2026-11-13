"""Enterprise forwardAuth: non-owners (admins included) need an active takeover."""
import pytest

from app.models import SessionTakeover
from app.models import _now as utcnow
from tests.test_instance_auth_check import _fwd, _inst, _owner, _uid, auth


def _tk(iid, actor, ended=False):
    return SessionTakeover(instance_id=iid, actor_id=actor, mode="view", reason="r",
                           ended_at=utcnow() if ended else None)


@pytest.fixture
def enterprise(monkeypatch):
    monkeypatch.setenv("STYX_PROFILE", "enterprise")


async def _get(c):
    return (await c.get(auth(), headers=_fwd("/i/dev/"))).status_code


@pytest.mark.asyncio
async def test_owner_allowed(enterprise, member_client, session):
    await _inst(session, await _uid(session, "member"))
    assert await _get(member_client) == 200


@pytest.mark.asyncio
async def test_active_takeover_actor_allowed(enterprise, admin_client, session):
    await _inst(session, await _owner(session))
    session.add(_tk("i-dev", await _uid(session, "admin")))
    await session.commit()
    assert await _get(admin_client) == 200


@pytest.mark.asyncio
async def test_admin_without_takeover_forbidden(enterprise, admin_client, session):
    await _inst(session, await _owner(session))
    assert await _get(admin_client) == 403


@pytest.mark.asyncio
async def test_ended_takeover_forbidden(enterprise, admin_client, session):
    await _inst(session, await _owner(session))
    session.add(_tk("i-dev", await _uid(session, "admin"), ended=True))
    await session.commit()
    assert await _get(admin_client) == 403


@pytest.mark.asyncio
async def test_other_user_forbidden_despite_others_takeover(enterprise, second_member_client, session):
    owner = await _owner(session)
    await _inst(session, owner)
    session.add(_tk("i-dev", owner))
    await session.commit()
    assert await _get(second_member_client) == 403


@pytest.mark.asyncio
async def test_homelab_admin_allowed(admin_client, session):
    await _inst(session, await _owner(session))
    assert await _get(admin_client) == 200
