import logging
from datetime import datetime, timedelta

import httpx
import pytest
from sqlmodel import select

from app.models import Instance, ServiceTemplate, SessionTakeover, User
from app.services import takeover_alert

URL = "https://matrix.example/hook"


def _t():
    return SessionTakeover(instance_id="i-1", actor_id="actor-1", user_id="user-1",
                           mode="control", reason="ticket 42",
                           started_at=datetime(2026, 11, 1, 12, 30))


async def test_post_sent():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(200)

    assert await takeover_alert.notify_start(_t(), URL, transport=httpx.MockTransport(handler))
    body = seen[0].content.decode()
    for s in ("actor-1", "user-1", "control", "ticket 42", "2026-11-01 12:30"):
        assert s in body


async def test_url_unset_skipped():
    def handler(req):
        raise AssertionError("must not post")

    assert not await takeover_alert.notify_start(_t(), "", transport=httpx.MockTransport(handler))


async def test_post_failure_logged_not_raised(caplog):
    caplog.set_level(logging.WARNING)
    assert not await takeover_alert.notify_start(
        _t(), URL, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert "takeover alert failed" in caplog.text


@pytest.fixture
async def inst(session):
    t = ServiceTemplate(name="t", display_name="T", image="img")
    session.add(t)
    await session.commit()
    o = User(username="owner", password_hash="x", role="member", is_active=True)
    session.add(o)
    await session.commit()
    session.add(Instance(id="i-1", template_id=t.id, name="n", subdomain="s1", owner_id=o.id))
    await session.commit()


async def test_start_survives_alert_failure(admin_client, inst, session, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(takeover_alert, "notify_start", boom)
    r = await admin_client.post("/api/instances/i-1/takeover",
                                json={"mode": "view", "reason": "x"})
    assert r.status_code == 201
    assert (await session.exec(select(SessionTakeover))).one()


async def test_start_posts_alert(admin_client, inst, monkeypatch):
    calls = []

    async def fake(t, url, **k):
        calls.append((t.mode, url))
        return True

    monkeypatch.setenv("MATRIX_SECURITY_WEBHOOK_URL", URL)
    monkeypatch.setattr(takeover_alert, "notify_start", fake)
    r = await admin_client.post("/api/instances/i-1/takeover",
                                json={"mode": "view", "reason": "x"})
    assert r.status_code == 201 and calls == [("view", URL)]


async def _seed(session):
    now = datetime(2026, 11, 1, 12, 0)
    for i in range(3):
        session.add(SessionTakeover(instance_id=f"i-{i}", actor_id="a", mode="view",
                                    reason=f"r{i}", started_at=now + timedelta(days=i)))
    await session.commit()


async def test_list_admin_newest_first_and_since(admin_client, session):
    await _seed(session)
    r = await admin_client.get("/api/admin/takeovers")
    assert [x["reason"] for x in r.json()] == ["r2", "r1", "r0"]
    r = await admin_client.get("/api/admin/takeovers",
                               params={"since": "2026-11-02T18:00:00"})
    assert [x["reason"] for x in r.json()] == ["r2"]


@pytest.mark.parametrize("staff,code", [("auditor", 200), ("platform-admin", 200),
                                        ("help-desk", 403), ("group-manager", 403), ("", 403)])
async def test_list_roles(member_client, session, staff, code):
    u = (await session.exec(select(User).where(User.username == "member"))).one()
    u.staff_role = staff
    session.add(u)
    await session.commit()
    assert (await member_client.get("/api/admin/takeovers")).status_code == code
