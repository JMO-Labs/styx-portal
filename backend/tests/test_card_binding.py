"""First-login card binding and admin review queue (styx-portal#122, ADR-0016)."""
import json
from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from app.models import ApprovedRequest, AuditLog, CardReview
from app.services import card_binding

EDIPI = "1234567890"
UUID = "urn:uuid:9f1c2d3e-0000-4000-8000-123456789abc"
KC = "kc-user-1"


@pytest.fixture
def kc(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr(card_binding.kc_admin, "set_attributes", m)
    return m


async def req(session, ext="r1", card="CAC", email="ada@example.mil", edipi=EDIPI):
    r = ApprovedRequest(idempotency_key="k" + ext, body_hash="h", approval_id="a" + ext,
                        external_id=ext, approver_email="m@x.mil", card_type=card,
                        person_type="employee",
                        subject={"name": "Ada", "email": email, "edipi": edipi})
    session.add(r)
    await session.commit()
    return r


def cac(**kw):
    return {"sub": KC, "card_type": "CAC", "edipi": EDIPI, **kw}


def piv(**kw):
    return {"sub": KC, "card_type": "PIV", "cert_email": "ADA@example.mil", "card_id": UUID, **kw}


async def queue(session):
    return (await session.exec(select(CardReview))).all()


async def test_cac_exact_binds(session, kc):
    r = await req(session)
    assert await card_binding.bind_card(session, cac()) == "bound"
    kc.assert_awaited_once_with(KC, {"edipi": [EDIPI]})
    await session.refresh(r)
    assert r.status == "bound"
    assert await queue(session) == []
    assert (await session.exec(select(AuditLog).where(AuditLog.action == "card.bound"))).first()


@pytest.mark.parametrize("card", ["PIV", "PIV-I"])
async def test_piv_email_case_insensitive_binds(session, kc, card):
    r = await req(session, card=card, edipi=None)
    assert await card_binding.bind_card(session, piv(card_type=card)) == "bound"
    kc.assert_awaited_once_with(KC, {"card_uuid": [UUID]})
    await session.refresh(r)
    assert r.status == "bound"


async def test_cac_edipi_mismatch_queues(session, kc):
    r = await req(session, edipi="0000000001")
    assert await card_binding.bind_card(session, cac()) == "queued"
    kc.assert_not_awaited()
    await session.refresh(r)
    assert r.status == "pending_binding"
    assert len(await queue(session)) == 1


async def test_cac_name_only_match_queues(session, kc):
    await req(session, edipi="0000000001")
    assert await card_binding.bind_card(session, cac(name="Ada", email="ada@example.mil")) == "queued"
    kc.assert_not_awaited()


async def test_piv_partial_email_queues(session, kc):
    await req(session, card="PIV", edipi=None, email="ada@example.mil.evil")
    assert await card_binding.bind_card(session, piv()) == "queued"
    kc.assert_not_awaited()


async def test_piv_does_not_match_cac_request(session, kc):
    await req(session, card="CAC", email="ada@example.mil")
    assert await card_binding.bind_card(session, piv()) == "queued"


async def test_no_request_queues(session, kc):
    assert await card_binding.bind_card(session, cac()) == "queued"
    kc.assert_not_awaited()
    assert len(await queue(session)) == 1


async def test_several_matches_queue(session, kc):
    await req(session, ext="r1")
    await req(session, ext="r2")
    assert await card_binding.bind_card(session, cac()) == "queued"
    kc.assert_not_awaited()
    assert len(await queue(session)) == 1


async def test_already_bound_request_not_rebound(session, kc):
    r = await req(session)
    r.status = "bound"
    session.add(r)
    await session.commit()
    assert await card_binding.bind_card(session, cac()) == "queued"


async def test_no_card_ids_in_logs_or_audit(session, kc, caplog):
    caplog.set_level("DEBUG")
    await req(session)
    await card_binding.bind_card(session, cac())
    await card_binding.bind_card(session, {**cac(), "edipi": "5555555555"})
    await card_binding.bind_card(session, piv())
    rows = (await session.exec(select(AuditLog))).all()
    blob = json.dumps([r.detail for r in rows] + [r.resource for r in rows]) + caplog.text
    for secret in (EDIPI, "5555555555", UUID, "9f1c2d3e"):
        assert secret not in blob


# --- admin API ---

async def test_admin_list_and_reject(admin_client, session, kc):
    await card_binding.bind_card(session, cac())
    await session.commit()
    r = await admin_client.get("/api/admin/card-reviews")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1 and EDIPI not in r.text
    rid = items[0]["id"]
    r = await admin_client.post(f"/api/admin/card-reviews/{rid}/resolve",
                                json={"decision": "reject"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    kc.assert_not_awaited()
    assert (await admin_client.post(f"/api/admin/card-reviews/{rid}/resolve",
                                    json={"decision": "reject"})).status_code == 409
    assert (await session.exec(select(AuditLog).where(
        AuditLog.action == "card.review.rejected"))).first()


async def test_admin_approve_binds(admin_client, session, kc):
    ar = await req(session, edipi="0000000001")
    await card_binding.bind_card(session, cac())
    rid = (await queue(session))[0].id
    r = await admin_client.post(f"/api/admin/card-reviews/{rid}/resolve",
                                json={"decision": "approve", "request_id": ar.id})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    kc.assert_awaited_once_with(KC, {"edipi": [EDIPI]})
    await session.refresh(ar)
    assert ar.status == "bound"
    logs = (await session.exec(select(AuditLog))).all()
    assert EDIPI not in json.dumps([l.detail for l in logs])


async def test_approve_requires_request_id(admin_client, session, kc):
    await card_binding.bind_card(session, cac())
    rid = (await queue(session))[0].id
    r = await admin_client.post(f"/api/admin/card-reviews/{rid}/resolve",
                                json={"decision": "approve"})
    assert r.status_code == 422


async def test_admin_only(member_client):
    assert (await member_client.get("/api/admin/card-reviews")).status_code == 403
    assert (await member_client.post("/api/admin/card-reviews/x/resolve",
                                     json={"decision": "reject"})).status_code == 403
