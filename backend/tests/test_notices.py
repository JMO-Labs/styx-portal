from datetime import datetime, timezone

import pytest
from sqlmodel import select

from app.models import Notice, User
from app.services.notices import post_notice

DUE = datetime(2026, 12, 1)


async def _uid(session, name):
    u = (await session.exec(select(User).where(User.username == name))).one()
    return u.id


@pytest.mark.asyncio
async def test_post_notice_idempotent(session):
    u = User(username="n1", password_hash="x", role="user")
    session.add(u)
    await session.commit()
    a = await post_notice(session, u.id, "ageoff", "k1", "first", DUE)
    b = await post_notice(session, u.id, "ageoff", "k1", "second", DUE)
    assert a.id == b.id and b.message == "first"
    assert len((await session.exec(select(Notice))).all()) == 1
    c = await post_notice(session, u.id, "ageoff", "k2", "other", None)
    assert c.id != a.id


@pytest.mark.asyncio
async def test_list_only_own_undismissed(member_client, second_member_client, session):
    me, other = await _uid(session, "member"), await _uid(session, "member2")
    mine = await post_notice(session, me, "ageoff", "a", "mine", DUE)
    gone = await post_notice(session, me, "ageoff", "b", "dismissed", DUE)
    gone.dismissed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(gone)
    await post_notice(session, other, "ageoff", "a", "theirs", DUE)
    await session.commit()
    r = await member_client.get("/api/notices")
    assert r.status_code == 200
    assert [n["id"] for n in r.json()] == [mine.id]
    assert r.json()[0]["message"] == "mine"


@pytest.mark.asyncio
async def test_dismiss(member_client, session):
    me = await _uid(session, "member")
    n = await post_notice(session, me, "ageoff", "a", "m", DUE)
    r = await member_client.post(f"/api/notices/{n.id}/dismiss")
    assert r.status_code == 200
    await session.refresh(n)
    assert n.dismissed_at is not None
    assert (await member_client.get("/api/notices")).json() == []


@pytest.mark.asyncio
async def test_dismiss_other_users_notice_404(member_client, second_member_client, session):
    other = await _uid(session, "member2")
    n = await post_notice(session, other, "ageoff", "a", "m", DUE)
    r = await member_client.post(f"/api/notices/{n.id}/dismiss")
    assert r.status_code == 404
    await session.refresh(n)
    assert n.dismissed_at is None
