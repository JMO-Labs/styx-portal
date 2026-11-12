"""New-account review: provisioned API, business days, auto-suspend (#127)."""
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.models import AuditLog, User
from app.services.new_account_review import business_days_between, review_pass

MON = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def test_business_days_skip_weekend():
    fri = MON - timedelta(days=3)
    assert business_days_between(fri, MON) == 1          # Fri -> Mon
    assert business_days_between(MON, MON + timedelta(days=4)) == 4
    assert business_days_between(MON, MON + timedelta(days=7)) == 5
    sat = MON - timedelta(days=2)
    assert business_days_between(sat, MON) == 1          # Sat -> Mon
    assert business_days_between(MON, fri) == 0


async def _mk(session, name, created, **kw):
    u = User(username=name, password_hash="x", created_at=created, **kw)
    session.add(u)
    await session.commit()
    return u


async def test_list_admin_only_and_window(admin_client, session):
    now = datetime.now(timezone.utc)
    await _mk(session, "new1", now - timedelta(days=2))
    await _mk(session, "old1", now - timedelta(days=40))
    r = await admin_client.get("/api/admin/provisioned?days=14")
    assert r.status_code == 200
    rows = {x["username"]: x for x in r.json()}
    assert "new1" in rows and "old1" not in rows
    assert rows["new1"]["reviewed_at"] is None and rows["new1"]["status"] == "active"


async def test_list_requires_auth(client):
    assert (await client.get("/api/admin/provisioned")).status_code in (401, 403)


async def test_review_and_suspend_audited(admin_client, session):
    u = await _mk(session, "n2", datetime.now(timezone.utc))
    r = await admin_client.post(f"/api/admin/provisioned/{u.id}/review")
    assert r.status_code == 200 and r.json()["reviewed_at"]
    r = await admin_client.post(f"/api/admin/provisioned/{u.id}/suspend")
    assert r.status_code == 200
    await session.refresh(u)
    assert u.disabled_reason == "new_account_suspend" and u.disabled_at
    actions = {a.action for a in (await session.exec(select(AuditLog))).all()}
    assert {"account.reviewed", "account.disabled"} <= actions
    assert (await admin_client.post("/api/admin/provisioned/nope/review")).status_code == 404


async def test_review_pass_suspends_unreviewed_idempotent(session):
    now = MON + timedelta(days=1)   # Tue
    old = await _mk(session, "o", MON - timedelta(days=3))        # Fri -> 2 bd... Fri->Tue = 2
    older = await _mk(session, "oo", MON - timedelta(days=7))
    fresh = await _mk(session, "f", MON)                            # 1 bd
    rev = await _mk(session, "r", MON - timedelta(days=10), reviewed_at=MON)
    assert await review_pass(session, now=now) == 1                 # only 'oo' (>2)
    await session.refresh(older)
    assert older.disabled_reason == "unreviewed"
    for u in (old, fresh, rev):
        await session.refresh(u)
        assert u.disabled_at is None
    assert await review_pass(session, now=now) == 0
