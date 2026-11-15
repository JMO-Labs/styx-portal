"""Edge-case coverage for app/routers/auth_link.py."""
import pytest
from unittest.mock import AsyncMock, patch
from sqlmodel import select

from app.models import FederatedIdentity, User
from app.schemas import OAuthIdentity
from app.security import oauth
from app.services import federation
from tests.test_link import _seed

CB = "/api/auth/link/github/callback"


async def _admin(session) -> User:
    return (await session.exec(select(User).where(User.username == "admin"))).first()


def _loc(resp) -> str:
    return resp.headers["location"]


@pytest.mark.asyncio
async def test_link_start_unknown_provider_404(admin_client):
    r = await admin_client.get("/api/auth/link/nope/start", follow_redirects=False)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_callback_missing_state_cookie(admin_client, session):
    await _seed(session)
    r = await admin_client.get(f"{CB}?state=S", follow_redirects=False)
    assert "link=missing_state" in _loc(r)


@pytest.mark.asyncio
async def test_callback_undecodable_cookie(admin_client, session):
    await _seed(session)
    admin_client.cookies.set("oauth_tx", "garbage")
    r = await admin_client.get(f"{CB}?state=S", follow_redirects=False)
    assert "link=bad_state" in _loc(r)


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,mode,qstate", [
    ("other", "link", "S"), ("github", "login", "S"), ("github", "link", "WRONG")])
async def test_callback_state_mismatch(admin_client, session, provider, mode, qstate):
    await _seed(session)
    u = await _admin(session)
    admin_client.cookies.set("oauth_tx", oauth.pack_tx(provider, "S", "V", mode, u.id))
    r = await admin_client.get(f"{CB}?state={qstate}", follow_redirects=False)
    assert "link=bad_state" in _loc(r)


@pytest.mark.asyncio
async def test_callback_provider_missing(admin_client, session):
    u = await _admin(session)  # no provider seeded
    admin_client.cookies.set("oauth_tx", oauth.pack_tx("github", "S", "V", "link", u.id))
    r = await admin_client.get(f"{CB}?state=S", follow_redirects=False)
    assert "link=error" in _loc(r)


@pytest.mark.asyncio
@pytest.mark.parametrize("exc,code", [
    (federation.NotAuthorized("taken"), "conflict"), (RuntimeError("boom"), "error")])
async def test_callback_link_failures(admin_client, session, exc, code):
    await _seed(session)
    u = await _admin(session)
    admin_client.cookies.set("oauth_tx", oauth.pack_tx("github", "S", "V", "link", u.id))
    ident = OAuthIdentity(sub="gh-1", email="a@x.com", email_verified=True, claims={})
    with patch("app.security.oauth.fetch_identity", AsyncMock(return_value=ident)), \
            patch("app.services.federation.link_identity", AsyncMock(side_effect=exc)):
        r = await admin_client.get(f"{CB}?state=S", follow_redirects=False)
    assert f"link={code}" in _loc(r)


@pytest.mark.asyncio
async def test_unlink_not_linked_404(admin_client):
    r = await admin_client.delete("/api/auth/link/github")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unlink_only_login_method_rejected(admin_client, session):
    u = await _admin(session)
    u.password_hash = "!disabled"
    session.add(u)
    session.add(FederatedIdentity(user_id=u.id, provider="github", subject="gh-1",
                                  email="a@x.com"))
    await session.commit()
    r = await admin_client.delete("/api/auth/link/github")
    assert r.status_code == 400
    rows = (await session.exec(select(FederatedIdentity))).all()
    assert len(rows) == 1
