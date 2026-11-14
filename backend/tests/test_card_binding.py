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
def account():
    """Keycloak representation of the logged-in user (claims["sub"])."""
    return {"id": KC, "username": "ada.l", "email": "Ada@Example.mil", "attributes": {}}


@pytest.fixture
def holders():
    """Keycloak user ids already holding the presented card key."""
    return []


@pytest.fixture
def kc(monkeypatch, account, holders):
    m = AsyncMock()
    monkeypatch.setattr(card_binding.kc_admin, "set_attributes", m)
    monkeypatch.setattr(card_binding.kc_admin, "get_attributes", AsyncMock(return_value={}))
    monkeypatch.setattr(card_binding.kc_admin, "get_user", AsyncMock(return_value=account))
    monkeypatch.setattr(card_binding.kc_admin, "find_user_ids_by_attribute",
                        AsyncMock(return_value=holders))
    return m


async def req(session, ext="r1", card="CAC", email="ada@example.mil", edipi=EDIPI, **extra):
    r = ApprovedRequest(idempotency_key="k" + ext, body_hash="h", approval_id="a" + ext,
                        external_id=ext, approver_email="m@x.mil", card_type=card,
                        person_type="employee",
                        subject={"name": "Ada", "email": email, "edipi": edipi, **extra})
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


async def test_bind_keeps_existing_attributes(session, kc, account):
    account["attributes"] = {"org": ["navy"], "edipi": [EDIPI]}
    await req(session)
    assert await card_binding.bind_card(session, cac()) == "bound"
    kc.assert_awaited_once_with(KC, {"org": ["navy"], "edipi": [EDIPI]})


async def test_bind_without_commit_leaves_transaction_open(session, kc, monkeypatch):
    r = await req(session)
    commit = AsyncMock()
    monkeypatch.setattr(session, "commit", commit)
    await card_binding.bind(session, KC, r, cac(), commit=False)
    commit.assert_not_awaited()
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
    # Only our own loggers: the DB driver's DEBUG echo of stored request rows is out of scope.
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    blob = json.dumps([r.detail for r in rows] + [r.resource for r in rows]) + app_logs
    for secret in (EDIPI, "5555555555", UUID, "9f1c2d3e"):
        assert secret not in blob


# --- refusals (styx-portal#350) ---

async def reasons(session):
    return [q.reason for q in await queue(session)]


async def queued_audit(session):
    rows = (await session.exec(select(AuditLog).where(
        AuditLog.action == "card.review.queued"))).all()
    return [r.detail["reason"] for r in rows]


async def assert_refused(session, kc, r, reason):
    kc.assert_not_awaited()
    await session.refresh(r)
    assert r.status == "pending_binding"
    assert await reasons(session) == [reason]
    assert await queued_audit(session) == [reason]


async def test_request_kc_user_id_same_user_binds(session, kc, account):
    account["email"] = "someone.else@example.mil"   # kc_user_id wins over email
    await req(session, kc_user_id=KC)
    assert await card_binding.bind_card(session, cac()) == "bound"


async def test_request_for_other_kc_user_refused(session, kc):
    r = await req(session, kc_user_id="kc-user-A")
    assert await card_binding.bind_card(session, cac()) == "queued"
    await assert_refused(session, kc, r, "subject_mismatch")


async def test_other_account_email_refused(session, kc, account):
    account["email"] = "bob@example.mil"
    r = await req(session)
    assert await card_binding.bind_card(session, cac()) == "queued"
    await assert_refused(session, kc, r, "subject_mismatch")


@pytest.mark.parametrize("card", ["PIV", "PIV-I"])
async def test_piv_cert_of_other_user_refused(session, kc, account, card):
    account["email"] = "bob@example.mil"
    r = await req(session, card=card, edipi=None)
    assert await card_binding.bind_card(session, piv(card_type=card)) == "queued"
    await assert_refused(session, kc, r, "subject_mismatch")


async def test_username_match_binds_without_email(session, kc, account):
    account.pop("email")
    await req(session, username="ada.l")
    assert await card_binding.bind_card(session, cac()) == "bound"


async def test_blank_identity_never_matches(session, kc, account):
    account.update(email="", username="")
    r = await req(session, email="", username="")
    assert await card_binding.bind_card(session, cac()) == "queued"
    await assert_refused(session, kc, r, "subject_mismatch")


@pytest.mark.parametrize("holders", [["kc-user-A"], [KC, "kc-user-A"]])
async def test_card_on_other_user_refused(session, kc, holders):
    r = await req(session)
    assert await card_binding.bind_card(session, cac()) == "queued"
    await assert_refused(session, kc, r, "card_in_use")
    card_binding.kc_admin.find_user_ids_by_attribute.assert_awaited_once_with("edipi", EDIPI)


@pytest.mark.parametrize("holders", [[KC]])
async def test_card_already_on_same_user_binds(session, kc, holders):
    await req(session)
    assert await card_binding.bind_card(session, cac()) == "bound"


async def test_existing_different_card_refused(session, kc, account):
    account["attributes"] = {"edipi": ["0000000001"]}
    r = await req(session)
    assert await card_binding.bind_card(session, cac()) == "queued"
    await assert_refused(session, kc, r, "card_conflict")


async def test_existing_different_piv_card_refused(session, kc, account):
    account["attributes"] = {"card_uuid": ["urn:uuid:other"]}
    r = await req(session, card="PIV", edipi=None)
    assert await card_binding.bind_card(session, piv()) == "queued"
    await assert_refused(session, kc, r, "card_conflict")


async def test_happy_path_audited(session, kc):
    await req(session, kc_user_id=KC)
    assert await card_binding.bind_card(session, cac()) == "bound"
    row = (await session.exec(select(AuditLog).where(AuditLog.action == "card.bound"))).one()
    assert row.detail["kc_user_id"] == KC
    assert await queue(session) == []


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
    assert EDIPI not in json.dumps([row.detail for row in logs])


async def test_approve_without_kc_user_conflicts(admin_client, session, kc):
    ar = await req(session, edipi="0000000001")
    await card_binding.bind_card(session, {"card_type": "CAC", "edipi": EDIPI})  # no sub
    item = (await queue(session))[0]
    assert item.reason == "invalid_claims" and item.kc_user_id == ""
    r = await admin_client.post(f"/api/admin/card-reviews/{item.id}/resolve",
                                json={"decision": "approve", "request_id": ar.id})
    assert r.status_code == 409
    kc.assert_not_awaited()
    await session.refresh(ar)
    assert ar.status == "pending_binding"


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
