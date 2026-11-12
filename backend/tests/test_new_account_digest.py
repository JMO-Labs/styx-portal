"""New-account digest: build, API, Matrix webhook post (#136)."""
import httpx
from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app.models import AuditLog, User
from app.services import new_account_digest as nd

NOW = datetime(2026, 11, 12, 9, 0, tzinfo=timezone.utc)


async def _mk(session, name, created, **kw):
    u = User(username=name, password_hash="x", created_at=created, **kw)
    session.add(u)
    await session.commit()
    return u


async def _seed(session):
    await _mk(session, "fresh", NOW - timedelta(hours=3))
    await _mk(session, "pending", NOW - timedelta(days=5))
    await _mk(session, "done", NOW - timedelta(days=5), reviewed_at=NOW)
    await _mk(session, "freshreviewed", NOW - timedelta(hours=2), reviewed_at=NOW)


async def test_build_digest(session):
    await _seed(session)
    text = await nd.build_digest(session, NOW)
    assert "fresh" in text and "pending" in text and "freshreviewed" in text
    assert "done" not in text.replace("freshreviewed", "")


async def test_build_digest_empty(session):
    assert "No new" in await nd.build_digest(session, NOW)


async def test_digest_endpoint(admin_client, session):
    await _mk(session, "newbie", datetime.now(timezone.utc))
    r = await admin_client.get("/api/admin/provisioned/digest")
    assert r.status_code == 200 and "newbie" in r.json()["digest"]


async def test_digest_endpoint_requires_admin(client):
    assert (await client.get("/api/admin/provisioned/digest")).status_code in (401, 403)


async def test_post_when_set(session, monkeypatch):
    await _seed(session)
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        return httpx.Response(200)
    r = await nd.run_once(session, "http://matrix.test/hook", NOW,
                          transport=httpx.MockTransport(handler))
    assert r is True and len(seen) == 1 and b"pending" in seen[0].content


async def test_skipped_when_unset(session, caplog):
    caplog.set_level("INFO")
    assert await nd.run_once(session, "", NOW) is False
    assert "MATRIX_DIGEST_WEBHOOK_URL" in caplog.text


async def test_failure_logged_and_audited(session):
    def handler(req):
        return httpx.Response(500)
    r = await nd.run_once(session, "http://matrix.test/hook", NOW,
                          transport=httpx.MockTransport(handler))
    assert r is False
    rows = (await session.exec(select(AuditLog).where(
        AuditLog.action == "account.digest_failed"))).all()
    assert len(rows) == 1
