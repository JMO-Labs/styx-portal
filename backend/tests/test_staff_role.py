import pytest

from sqlmodel import select

from app.models import User
from app.security.deps import can_takeover
from app.services import federation


async def _user(session, role="user", staff_role=""):
    u = User(username="kc", email="kc@x.io", password_hash="!", role=role, staff_role=staff_role)
    session.add(u)
    await session.commit()
    return u


@pytest.mark.parametrize("staff,role,ok", [
    ("platform-admin", "user", True),
    ("help-desk", "user", True),
    ("auditor", "user", False),
    ("group-manager", "user", False),
    ("", "user", False),
    ("", "admin", True),
    ("auditor", "admin", True),
])
def test_can_takeover(staff, role, ok):
    assert can_takeover(User(username="u", password_hash="!", role=role, staff_role=staff)) is ok


def test_default_staff_role_empty():
    assert User(username="u", password_hash="!").staff_role == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("roles,expected", [
    (["group-manager", "auditor"], "auditor"),
    (["auditor", "help-desk", "group-manager"], "help-desk"),
    (["help-desk", "platform-admin"], "platform-admin"),
    (["group-manager"], "group-manager"),
    (["offline_access", "other"], ""),
    ([], ""),
    ("help-desk", "help-desk"),
])
async def test_sync_staff_role(session, roles, expected):
    u = await _user(session)
    await federation.sync_staff_role(session, u, {"realm_roles": roles})
    await session.refresh(u)
    assert u.staff_role == expected


@pytest.mark.asyncio
async def test_sync_staff_role_custom_claim_and_revocation(session):
    u = await _user(session, staff_role="help-desk")
    rm = {"staff_role_claim": "kc_roles"}
    await federation.sync_staff_role(session, u, {"realm_roles": ["platform-admin"]}, rm)
    assert u.staff_role == ""  # default claim ignored, custom claim absent
    await federation.sync_staff_role(session, u, {"kc_roles": ["auditor"]}, rm)
    assert u.staff_role == "auditor"


@pytest.mark.asyncio
async def test_oidc_callback_syncs_staff_role(client, session):
    from unittest.mock import AsyncMock, patch

    from sqlmodel import select

    from app.models import Invite
    from app.schemas import OAuthIdentity
    from tests.db_helpers import ensure_user
    from tests.test_oauth_router import _seed_provider

    await _seed_provider(session)
    await ensure_user(session, "a")
    session.add(Invite(token_hash="h", email="kc@x.com", role="user", created_by="a"))
    await session.commit()
    with patch("app.security.oauth.build_authorize",
               AsyncMock(return_value=("https://idp/auth", "STATE", "VERIFIER"))):
        await client.get("/api/auth/oauth/google/start", follow_redirects=False)
    ident = OAuthIdentity(sub="kc-1", email="kc@x.com", email_verified=True,
                          claims={"realm_roles": ["auditor", "help-desk"]})
    with patch("app.security.oauth.fetch_identity", AsyncMock(return_value=ident)):
        r = await client.get("/api/auth/oauth/google/callback?state=STATE&code=abc",
                             follow_redirects=False)
    assert r.status_code == 302
    assert "access_token" in r.cookies
    session.expire_all()
    u = (await session.exec(select(User).where(User.email == "kc@x.com"))).one()
    assert u.staff_role == "help-desk"


@pytest.mark.asyncio
async def test_me_exposes_can_takeover(member_client, session):
    # member_client shares one client; check member first, then promote via staff_role.
    assert (await member_client.get("/api/auth/me")).json()["can_takeover"] is False
    member = (await session.exec(select(User).where(User.username == "member"))).first()
    member.staff_role = "help-desk"
    session.add(member)
    await session.commit()
    assert (await member_client.get("/api/auth/me")).json()["can_takeover"] is True


@pytest.mark.asyncio
async def test_me_admin_can_takeover(admin_client):
    assert (await admin_client.get("/api/auth/me")).json()["can_takeover"] is True


@pytest.mark.asyncio
async def test_me_exposes_effective_staff_role(member_client, session):
    assert (await member_client.get("/api/auth/me")).json()["staff_role"] == ""
    member = (await session.exec(select(User).where(User.username == "member"))).first()
    member.staff_role = "auditor"
    session.add(member)
    await session.commit()
    assert (await member_client.get("/api/auth/me")).json()["staff_role"] == "auditor"


@pytest.mark.asyncio
async def test_me_admin_effective_staff_role(admin_client):
    assert (await admin_client.get("/api/auth/me")).json()["staff_role"] == "platform-admin"
