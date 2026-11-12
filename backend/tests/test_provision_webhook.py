"""POST /api/provision/requests: schema, policy, idempotency, audit (styx-portal#120)."""
import base64
import copy
import hashlib
import json

import pytest
from sqlalchemy import func
from sqlmodel import select

from app.models import ApprovedRequest
from app.routers import provision as prov
from app.security import provision_auth as pa

DER = b"\x30\x82fake-der"
TOKEN = "tok-secret-value"
HOST = "provision.example.test"
APPROVAL = "11111111-2222-3333-4444-555555555555"
EDIPI = "1234567890"
EXT = "urn:styx:scim:schemas:provisioning:1.0:Request"


def body(**ext):
    e = {"approvalId": APPROVAL, "approverEmail": "mgr@example.mil", "cardType": "CAC",
         "edipi": EDIPI, "groups": ["eng"], "personType": "employee"}
    e.update(ext)
    return {"schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"], "externalId": "req-1",
            "name": {"givenName": "Ada", "familyName": "Lovelace"},
            "emails": [{"value": "ada@example.mil"}], "active": True, EXT: e}


@pytest.fixture(autouse=True)
def cfg(monkeypatch):
    monkeypatch.setattr(pa._settings, "PROVISION_HOST", HOST)
    monkeypatch.setattr(pa._settings, "PROVISION_BEARER_TOKEN", TOKEN)
    monkeypatch.setattr(pa._settings, "PROVISION_CLIENT_CERT_FINGERPRINTS",
                        hashlib.sha256(DER).hexdigest())
    monkeypatch.setattr(prov._settings, "KEYCLOAK_ADMIN_GROUPS", "kc-admins, root")
    monkeypatch.setattr(prov._settings, "PROVISION_GROUP_MANAGERS",
                        json.dumps({"eng": ["mgr@example.mil"], "ops": ["mgr@example.mil"],
                                    "root": ["mgr@example.mil"]}))


def hdr(key="k1", **kw):
    h = {"Host": HOST, "Client-Cert": base64.b64encode(DER).decode(),
         "Authorization": f"Bearer {TOKEN}", "Idempotency-Key": key}
    h.update(kw)
    return {k: v for k, v in h.items() if v is not None}


async def post(client, b, **kw):
    return await client.post("/api/provision/requests", json=b, headers=hdr(**kw))


@pytest.fixture
def events(monkeypatch):
    out = []
    monkeypatch.setattr("app.services.audit.emit", out.append)
    return lambda: out


async def rows(session):
    return (await session.exec(select(func.count()).select_from(ApprovedRequest))).one()


async def test_accept_stores_pending_binding(client, session, events):
    r = await post(client, body())
    assert r.status_code == 201
    assert r.json()["status"] == "pending_binding"
    assert await rows(session) == 1
    row = (await session.exec(select(ApprovedRequest))).one()
    assert row.status == "pending_binding" and row.approval_id == APPROVAL
    (ev,) = [e for e in events() if e["event"]["action"] == "provision.request.accepted"]
    flat = json.dumps(ev)
    assert EDIPI not in flat and TOKEN not in flat


async def test_invalid_body_422_audited(client, session, events):
    b = body()
    b["bogus"] = 1
    r = await post(client, b)
    assert r.status_code == 422
    assert await rows(session) == 0
    assert [e for e in events() if e["event"]["action"] == "provision.request.invalid"]


def actions(events, name):
    return [e for e in events() if e["event"]["action"] == name]


async def test_not_json_422(client, events):
    r = await client.post("/api/provision/requests", content=b"{x", headers=hdr())
    assert r.status_code == 422
    assert len(actions(events, "provision.request.invalid")) == 1


async def test_missing_idempotency_key_400(client, events):
    r = await post(client, body(), key=None)
    assert r.status_code == 400
    assert r.json()["detail"] == "IDEMPOTENCY_KEY_MISSING"
    assert len(actions(events, "provision.request.invalid")) == 1


async def test_oversized_idempotency_key_400(client, session, events):
    big = "k" * 129
    r = await post(client, body(), key=big)
    assert r.status_code == 400
    assert r.json()["detail"] == "IDEMPOTENCY_KEY_INVALID"
    assert await rows(session) == 0
    (ev,) = actions(events, "provision.request.invalid")
    assert big not in json.dumps(ev)


async def test_group_manager_keys_case_insensitive(client, monkeypatch):
    monkeypatch.setattr(prov._settings, "PROVISION_GROUP_MANAGERS",
                        json.dumps({"ENG": ["mgr@example.mil"]}))
    r = await post(client, body(groups=["eng"], approverEmail="mgr@example.mil"))
    assert r.status_code == 201


async def test_unauthenticated_rejected(client, session):
    r = await post(client, body(), Authorization="Bearer nope")
    assert r.status_code == 401
    assert await rows(session) == 0


async def test_admin_group_403_audited(client, session, events):
    r = await post(client, body(groups=["eng", "root"]))
    assert r.status_code == 403
    assert await rows(session) == 0
    (ev,) = [e for e in events() if e["event"]["action"] == "provision.request.denied"]
    assert EDIPI not in json.dumps(ev)


async def test_unknown_approver_403_audited(client, session, events):
    r = await post(client, body(approverEmail="rando@example.mil"))
    assert r.status_code == 403
    assert r.json()["detail"] == "APPROVER_UNKNOWN"
    assert await rows(session) == 0
    assert [e for e in events() if e["event"]["action"] == "provision.request.denied"]


async def test_approver_must_manage_every_group(client, monkeypatch):
    monkeypatch.setattr(prov._settings, "PROVISION_GROUP_MANAGERS",
                        json.dumps({"eng": ["mgr@example.mil"], "ops": ["other@example.mil"]}))
    r = await post(client, body(groups=["eng", "ops"]))
    assert r.status_code == 403


async def test_replay_returns_original_no_new_row(client, session, events):
    first = await post(client, body())
    second = await post(client, body())
    assert second.status_code == first.status_code == 201
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replay"] == "true"
    assert await rows(session) == 1
    acts = [e["event"]["action"] for e in events()]
    assert acts.count("provision.request.accepted") == 1
    assert acts.count("provision.request.replay") == 1


async def test_same_key_different_body_409(client, session, events):
    await post(client, body())
    b = copy.deepcopy(body())
    b[EXT]["groups"] = ["eng", "ops"]
    r = await post(client, b)
    assert r.status_code == 409
    assert r.json()["detail"] == "IDEMPOTENCY_CONFLICT"
    assert await rows(session) == 1
    assert [e for e in events() if e["event"]["action"] == "provision.request.conflict"]


async def test_approval_reused_with_new_key_409(client, session):
    await post(client, body())
    r = await post(client, body(), key="k2")
    assert r.status_code == 409
    assert r.json()["detail"] == "APPROVAL_REUSED"
    assert await rows(session) == 1


async def test_external_id_exists_new_key_409(client, session):
    await post(client, body())
    b = body(approvalId="99999999-2222-3333-4444-555555555555")
    r = await post(client, b, key="k2")
    assert r.status_code == 409
    assert r.json()["detail"] == "USER_EXISTS"


async def test_webhook_calls_provision(client, monkeypatch):
    seen = []

    async def fake(session, row, op="create"):
        seen.append((row.external_id, op))
        return row
    monkeypatch.setattr(prov, "provision", fake)
    assert (await post(client, body())).status_code == 201
    assert seen == [("req-1", "create")]


@pytest.mark.parametrize("raw", ["{not json", "nope"])
def test_managers_bad_json_is_empty(monkeypatch, raw):
    monkeypatch.setattr(prov._settings, "PROVISION_GROUP_MANAGERS", raw)
    assert prov._managers() == {}


async def test_flush_race_returns_409_audited(client, session, events, monkeypatch):
    from sqlalchemy.exc import IntegrityError
    from sqlmodel.ext.asyncio.session import AsyncSession

    async def boom(self, *a, **kw):
        raise IntegrityError("insert", {}, Exception("dup"))

    monkeypatch.setattr(AsyncSession, "flush", boom)
    r = await post(client, body())
    assert r.status_code == 409 and r.json()["detail"] == "APPROVAL_REUSED"
    assert await rows(session) == 0
    assert any(e["event"]["action"] == "provision.request.conflict" for e in events())


async def test_replay_of_failed_row_retries_provisioning(client, session, monkeypatch):
    seen = []

    async def fake(session, row, op="create"):
        seen.append(row.status)
        row.status = "provisioned"
        return row
    monkeypatch.setattr(prov, "provision", fake)
    await post(client, body())
    row = (await session.exec(select(prov.ApprovedRequest))).one()
    row.status = "failed"
    session.add(row)
    await session.commit()
    seen.clear()
    r = await post(client, body())
    assert r.status_code == 201
    assert seen == ["failed"]
    assert r.headers["Idempotent-Replay"] == "true"
