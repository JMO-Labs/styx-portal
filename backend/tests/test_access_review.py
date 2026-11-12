from unittest.mock import AsyncMock

import pytest
from sqlmodel import select

from app.models import AccessReviewDecision, AuditLog, FederatedIdentity, Group, User, UserGroup
from app.security.passwords import hash_password

Q = "2026-Q4"


@pytest.fixture
async def setup(session):
    mgr = (await session.exec(select(User).where(User.username == "member"))).first()
    if mgr is None:
        mgr = User(username="member", email="m@x.io", password_hash=hash_password("x" * 20), role="member")
        session.add(mgr)
    other = User(username="other", email="o@x.io", password_hash=hash_password("x" * 20), role="user")
    target = User(username="alice", email="a@x.io", password_hash=hash_password("x" * 20), role="user")
    session.add_all([other, target])
    await session.flush()
    g1 = Group(name="g1", manager_user_id=mgr.id, kc_group_id="kc-g1")
    g2 = Group(name="g2", manager_user_id=other.id)
    session.add_all([g1, g2])
    await session.flush()
    session.add_all([UserGroup(user_id=target.id, group_id=g1.id),
                     UserGroup(user_id=target.id, group_id=g2.id)])
    await session.commit()
    return {"mgr": mgr, "target": target, "g1": g1, "g2": g2}


async def _audit(session, action):
    return (await session.exec(select(AuditLog).where(AuditLog.action == action))).one()


@pytest.fixture
def kc(monkeypatch):
    m = AsyncMock()
    monkeypatch.setattr("app.routers.access_review.kc_admin.remove_from_group", m)
    return m


async def test_model_fields(session):
    u = User(username="m", email="m@x.io", password_hash=hash_password("x" * 20), role="user")
    session.add(u)
    await session.flush()
    g = Group(name="x", manager_user_id=u.id, kc_group_id="k")
    session.add(g)
    await session.flush()
    session.add(AccessReviewDecision(group_id=g.id, user_id=u.id, quarter=Q,
                                     decision="certify", actor_id=u.id))
    await session.commit()
    assert (await session.exec(select(AccessReviewDecision))).one().quarter == Q


async def test_list_manager_scope(member_client, setup):
    r = await member_client.get(f"/api/access-review?quarter={Q}")
    assert r.status_code == 200
    rows = r.json()
    assert [x["group"] for x in rows] == ["g1"]
    assert rows[0]["username"] == "alice" and rows[0]["decision"] is None


async def test_list_forbidden_for_non_manager(session, member_client):
    r = await member_client.get(f"/api/access-review?quarter={Q}")
    assert r.status_code == 403


async def test_list_admin_sees_all(admin_client, session, setup):
    r = await admin_client.get(f"/api/access-review?quarter={Q}")
    assert {x["group"] for x in r.json()} == {"g1", "g2"}


async def test_certify(member_client, session, setup, kc):
    body = {"group_id": setup["g1"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "certify"}
    r = await member_client.post("/api/access-review/decisions", json=body)
    assert r.status_code == 201, r.text
    kc.assert_not_awaited()
    rows = (await member_client.get(f"/api/access-review?quarter={Q}")).json()
    assert rows[0]["decision"] == "certify"
    a = await _audit(session, "access_review.certify")
    assert a.resource == setup["g1"].id and a.detail["target_user"] == setup["target"].id


async def test_revoke(member_client, session, setup, kc):
    session.add(FederatedIdentity(user_id=setup["target"].id, provider="keycloak",
                                  subject="kc-sub-1"))
    await session.commit()
    body = {"group_id": setup["g1"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "revoke"}
    r = await member_client.post("/api/access-review/decisions", json=body)
    assert r.status_code == 201, r.text
    kc.assert_awaited_once_with("kc-sub-1", "kc-g1")
    assert await session.get(UserGroup, (setup["target"].id, setup["g1"].id)) is None
    a = await _audit(session, "access_review.revoke")
    assert a.resource == setup["g1"].id and a.detail["target_user"] == setup["target"].id
    assert "kc_skipped" not in a.detail


async def test_revoke_without_identity_skips_kc(member_client, session, setup, kc):
    session.add(FederatedIdentity(user_id=setup["target"].id, provider="google",
                                  subject="g-sub"))
    await session.commit()
    body = {"group_id": setup["g1"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "revoke"}
    assert (await member_client.post("/api/access-review/decisions", json=body)).status_code == 201
    kc.assert_not_awaited()
    a = await _audit(session, "access_review.revoke")
    assert a.detail["kc_skipped"] == "no identity"


async def test_duplicate_decision_conflict(member_client, setup, kc):
    body = {"group_id": setup["g1"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "certify"}
    assert (await member_client.post("/api/access-review/decisions", json=body)).status_code == 201
    r = await member_client.post("/api/access-review/decisions", json=body)
    assert r.status_code == 409


async def test_decision_non_member_404(member_client, setup, kc):
    body = {"group_id": setup["g1"].id, "user_id": setup["mgr"].id,
            "quarter": Q, "decision": "revoke"}
    r = await member_client.post("/api/access-review/decisions", json=body)
    assert r.status_code == 404
    kc.assert_not_awaited()


async def test_revoke_without_kc_group(admin_client, session, setup, kc):
    body = {"group_id": setup["g2"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "revoke"}
    assert (await admin_client.post("/api/access-review/decisions", json=body)).status_code == 201
    kc.assert_not_awaited()


async def test_manager_cannot_act_on_other_group(member_client, setup, kc):
    body = {"group_id": setup["g2"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "revoke"}
    r = await member_client.post("/api/access-review/decisions", json=body)
    assert r.status_code == 403
    kc.assert_not_awaited()


async def test_bad_decision_rejected(member_client, setup):
    body = {"group_id": setup["g1"].id, "user_id": setup["target"].id,
            "quarter": Q, "decision": "maybe"}
    assert (await member_client.post("/api/access-review/decisions", json=body)).status_code == 422


async def test_export_csv(member_client, setup, kc):
    await member_client.post("/api/access-review/decisions", json={
        "group_id": setup["g1"].id, "user_id": setup["target"].id,
        "quarter": Q, "decision": "certify"})
    r = await member_client.get(f"/api/access-review/export.csv?quarter={Q}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    lines = r.text.strip().splitlines()
    assert lines[0] == "quarter,group,username,email,decision,actor,decided_at"
    assert lines[1].startswith(f"{Q},g1,alice,a@x.io,certify,member,")


@pytest.mark.parametrize("v,out", [("=1+1", "'=1+1"), ("+x", "'+x"), ("-x", "'-x"),
                                   ("@x", "'@x"), ("alice", "alice"), ("", "")])
def test_safe_neutralises_formulas(v, out):
    from app.routers.access_review import _safe
    assert _safe(v) == out
