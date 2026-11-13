from datetime import timedelta, timezone

import pytest
from sqlmodel import select

from app.models import AuditLog, Instance, ServiceTemplate, SmartcardToken, User, _now

SECRET = "relay-secret-value"
HDR = {"X-Relay-Secret": SECRET}


@pytest.fixture(autouse=True)
def _relay_secret(monkeypatch):
    monkeypatch.setenv("SMARTCARD_RELAY_SECRET", SECRET)


async def _inst(session, owner_id, sub="sc1"):
    if not await session.get(ServiceTemplate, "t"):
        session.add(ServiceTemplate(id="t", name="tpl-t", display_name="T", image="img"))
        await session.commit()
    inst = Instance(template_id="t", name="n", subdomain=sub, owner_id=owner_id, status="running")
    session.add(inst)
    await session.commit()
    return inst.id


async def _me(c):
    return (await c.get("/api/auth/me")).json()


async def _mint(c, iid):
    r = await c.post(f"/api/instances/{iid}/smartcard-token")
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _redeem(c, token, iid, cert_user, headers=HDR):
    return c.post("/api/smartcard/redeem", headers=headers,
                  json={"token": token, "instance_id": iid, "cert_username": cert_user})


@pytest.mark.asyncio
async def test_mint_owner_only_and_hashed(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    r = await member_client.post(f"/api/instances/{iid}/smartcard-token")
    assert r.status_code == 200
    body = r.json()
    assert body["expires_in"] == 120 and len(body["token"]) >= 32
    row = (await session.exec(select(SmartcardToken))).one()
    assert row.token_hash != body["token"] and body["token"] not in row.token_hash
    assert (row.user_id, row.instance_id) == (me["id"], iid)
    assert timedelta(seconds=100) < row.expires_at.replace(tzinfo=timezone.utc) - _now() <= timedelta(seconds=120)


@pytest.mark.asyncio
async def test_mint_other_user_rejected(member_client, session):
    session.add(User(id="other", username="other", password_hash="x"))
    await session.commit()
    iid = await _inst(session, "other")
    r = await member_client.post(f"/api/instances/{iid}/smartcard-token")
    assert r.status_code in (403, 404)
    assert (await session.exec(select(SmartcardToken))).all() == []


@pytest.mark.asyncio
async def test_redeem_once(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    r = await _redeem(member_client, tok, iid, me["username"])
    assert r.status_code == 200 and r.json()["user_id"] == me["id"]
    assert (await _redeem(member_client, tok, iid, me["username"])).status_code == 403


@pytest.mark.asyncio
async def test_redeem_expired(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    row = (await session.exec(select(SmartcardToken))).one()
    row.expires_at = _now() - timedelta(seconds=1)
    session.add(row)
    await session.commit()
    assert (await _redeem(member_client, tok, iid, me["username"])).status_code == 403


@pytest.mark.asyncio
async def test_redeem_wrong_instance_cross_session(member_client, session):
    me = await _me(member_client)
    a = await _inst(session, me["id"], "sc-a")
    b = await _inst(session, me["id"], "sc-b")
    tok = await _mint(member_client, a)
    assert (await _redeem(member_client, tok, b, me["username"])).status_code == 403
    # a failed attempt must not burn the token for the right session
    assert (await _redeem(member_client, tok, a, me["username"])).status_code == 200


@pytest.mark.asyncio
async def test_redeem_wrong_cert_user(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    assert (await _redeem(member_client, tok, iid, "someone-else")).status_code == 403


@pytest.mark.asyncio
async def test_redeem_needs_relay_secret_not_cookie(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    for h in ({}, {"X-Relay-Secret": "wrong"}):
        assert (await _redeem(member_client, tok, iid, me["username"], h)).status_code == 403
    member_client.cookies.clear()
    member_client.headers.pop("X-CSRF-Token", None)
    assert (await _redeem(member_client, tok, iid, me["username"])).status_code == 200


@pytest.mark.asyncio
async def test_redeem_disabled_without_secret(member_client, session, monkeypatch):
    monkeypatch.setenv("SMARTCARD_RELAY_SECRET", "")
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    assert (await _redeem(member_client, tok, iid, me["username"], {"X-Relay-Secret": ""})).status_code == 403


@pytest.mark.asyncio
async def test_audit_events(member_client, session):
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    await _redeem(member_client, tok, iid, "bad")
    await _redeem(member_client, tok, iid, me["username"])
    rows = (await session.exec(select(AuditLog).where(AuditLog.action.like("smartcard.%")))).all()
    assert [r.action for r in rows] == [
        "smartcard.token.mint", "smartcard.redeem.fail", "smartcard.redeem.ok"]
    assert tok not in str([r.detail for r in rows])


@pytest.mark.asyncio
async def test_redeem_unknown_token_service(session):
    from app.services import smartcard_tokens as svc
    row, reason = await svc.redeem(session, "no-such-token", "i", "u")
    assert (row, reason) == (None, "unknown")


@pytest.mark.asyncio
async def test_redeem_lost_consume_race(member_client, session, monkeypatch):
    """A concurrent redeemer wins the atomic UPDATE; we must report 'used'."""
    from sqlalchemy.sql.dml import Update
    from app.services import smartcard_tokens as svc
    me = await _me(member_client)
    iid = await _inst(session, me["id"])
    tok = await _mint(member_client, iid)
    real_exec = session.exec

    async def racing_exec(stmt, *a, **kw):
        if isinstance(stmt, Update):
            await real_exec(stmt)  # the competing redeemer consumes first
        return await real_exec(stmt, *a, **kw)

    monkeypatch.setattr(session, "exec", racing_exec)
    row, reason = await svc.redeem(session, tok, iid, me["username"])
    assert row is not None and reason == "used"
