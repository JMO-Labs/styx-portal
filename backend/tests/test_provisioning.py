"""provision(): approved request -> Keycloak user with immutable POSIX UID (#121)."""
import json

import pytest
from sqlmodel import select

from app.models import ApprovedRequest, PosixUid
from app.services import provisioning as pv
from app.services.kc_admin import KeycloakAdminError


class FakeKC:
    def __init__(self):
        self.calls, self.fail_on = [], None

    def __getattr__(self, name):
        async def call(*a):
            self.calls.append((name, *a))
            if self.fail_on == name:
                raise KeycloakAdminError(f"{name} failed: 500")
            return "kc-1" if name == "create_user" else None
        return call

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def kc(monkeypatch):
    fake = FakeKC()
    monkeypatch.setattr(pv, "kc_admin", fake)
    return fake


@pytest.fixture
def events(monkeypatch):
    out = []
    monkeypatch.setattr("app.services.audit.emit", out.append)
    return out


async def make(session, **kw):
    row = ApprovedRequest(
        idempotency_key="k", body_hash="h", approval_id="a", external_id="e",
        approver_email="m@x.mil", groups=["eng", "ops"], card_type="CAC",
        person_type="employee",
        subject={"name": {"givenName": "Ada", "familyName": "Lovelace"},
                 "email": "ada@x.mil", "edipi": "123"}, **kw)
    session.add(row)
    await session.commit()
    return row


async def test_create(session, kc):
    row = await make(session)
    await pv.provision(session, row)
    uid = (await session.exec(select(PosixUid.uid))).one()
    assert kc.calls[0] == ("create_user", "ada.lovelace", "ada@x.mil", "Ada", "Lovelace")
    assert ("set_attributes", "kc-1", {"posix_uid": [str(uid)]}) in kc.calls
    assert [c for c in kc.calls if c[0] == "add_to_group"] == [
        ("add_to_group", "kc-1", "eng"), ("add_to_group", "kc-1", "ops")]
    assert row.status == "pending_binding"


async def test_update_never_touches_username_or_uid(session, kc):
    row = await make(session)
    await pv.provision(session, row)
    kc.calls.clear()
    row.subject = {**row.subject, "email": "new@x.mil",
                   "name": {"givenName": "Ada", "familyName": "King"}}
    row.groups = ["eng", "dev"]
    await pv.provision(session, row, "update")
    assert ("update_user", "kc-1", {"email": "new@x.mil", "firstName": "Ada",
                                    "lastName": "King"}) in kc.calls
    assert ("add_to_group", "kc-1", "dev") in kc.calls
    assert ("remove_from_group", "kc-1", "ops") in kc.calls
    assert "set_attributes" not in kc.names() and "create_user" not in kc.names()
    assert "username" not in json.dumps(kc.calls)


async def test_disable_keeps_uid(session, kc):
    row = await make(session)
    await pv.provision(session, row)
    kc.calls.clear()
    await pv.provision(session, row, "disable")
    assert kc.calls == [("disable_user", "kc-1")]
    assert row.status == "disabled"
    assert len((await session.exec(select(PosixUid))).all()) == 1


async def test_failure_marks_failed_audits_and_retry_is_idempotent(session, kc, events):
    row = await make(session)
    kc.fail_on = "set_attributes"
    await pv.provision(session, row)
    assert row.status == "failed"
    assert [e for e in events if e["event"]["action"] == "provision.failed"]
    kc.fail_on = None
    await pv.provision(session, row)
    assert kc.names().count("create_user") == 1
    assert row.status == "pending_binding"
    assert len((await session.exec(select(PosixUid))).all()) == 1


async def test_unknown_op_rejected(session, kc):
    with pytest.raises(ValueError):
        await pv.provision(session, await make(session), "bogus")
