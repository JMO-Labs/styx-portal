"""POST /api/users/{id}/remove-access (#124, ADR-0022)."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select

from app.models import AuditLog, FederatedIdentity, User
from app.services.kc_admin import KeycloakAdminError

KC = "app.routers.users.kc_admin.disable_user"


async def _target(session):
    u = User(username="bob", password_hash="x", role="user", is_active=True)
    session.add(u)
    await session.commit()
    session.add(FederatedIdentity(user_id=u.id, provider="keycloak", subject="kc-bob"))
    await session.commit()
    return u


@pytest.mark.asyncio
async def test_remove_access_disables_locally_and_in_keycloak(admin_client, session):
    u = await _target(session)
    with patch(KC, new=AsyncMock()) as kc:
        r = await admin_client.post(f"/api/users/{u.id}/remove-access")
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    kc.assert_awaited_once_with("kc-bob")
    await session.refresh(u)
    assert u.disabled_reason == "remove_access"


@pytest.mark.asyncio
async def test_non_admin_forbidden(member_client, session):
    u = await _target(session)
    r = await member_client.post(f"/api/users/{u.id}/remove-access")
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_keycloak_failure_still_disables_locally(admin_client, session):
    u = await _target(session)
    with patch(KC, new=AsyncMock(side_effect=KeycloakAdminError("boom"))):
        r = await admin_client.post(f"/api/users/{u.id}/remove-access")
    assert r.status_code == 502
    assert "Keycloak" in r.json()["detail"]
    await session.refresh(u)
    assert u.is_active is False and u.disabled_at is not None
    actions = [a.action for a in (await session.exec(select(AuditLog))).all()]
    assert "user.remove_access_kc_failed" in actions


@pytest.mark.asyncio
async def test_cannot_remove_own_access(admin_client):
    me = (await admin_client.get("/api/auth/me")).json()
    r = await admin_client.post(f"/api/users/{me['id']}/remove-access")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_unknown_user_404(admin_client):
    r = await admin_client.post("/api/users/nope/remove-access")
    assert r.status_code == 404
