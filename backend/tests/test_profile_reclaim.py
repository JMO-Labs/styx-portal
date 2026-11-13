from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest
from sqlmodel import select

from app.models import AuditLog, Instance, Notice, ServiceTemplate, User, UserProfile
from app.services.profile_reclaim import profile_reclaim_tick

NOW = datetime(2026, 12, 1)


async def _profile(session, last_used=None, created=None):
    u = User(username="pr", password_hash="x", role="user")
    t = ServiceTemplate(name="prt", display_name="PRT", image="img")
    session.add(u)
    session.add(t)
    await session.commit()
    p = UserProfile(user_id=u.id, template_id=t.id, volume_name="profile-v",
                    created_at=created or NOW - timedelta(days=100), last_used_at=last_used)
    session.add(p)
    await session.commit()
    return u, t, p


async def _notices(session):
    return (await session.exec(select(Notice).where(Notice.kind == "profile_reclaim"))).all()


@pytest.mark.asyncio
async def test_noop_when_not_leader(session):
    await _profile(session)
    rt = MagicMock()
    await profile_reclaim_tick(session, rt, NOW, lambda: False)
    await profile_reclaim_tick(session, rt, NOW, False)
    assert await _notices(session) == []


@pytest.mark.asyncio
async def test_notice_once_for_stale_profile(session):
    await _profile(session, last_used=NOW - timedelta(days=61))
    rt = MagicMock()
    for _ in range(2):
        await profile_reclaim_tick(session, rt, NOW, True)
    (n,) = await _notices(session)
    assert n.key == "profile-v" and n.due_at == NOW + timedelta(days=14)
    rt.remove_volume.assert_not_called()


@pytest.mark.asyncio
async def test_fresh_profile_untouched(session):
    await _profile(session, last_used=NOW - timedelta(days=10))
    await profile_reclaim_tick(session, MagicMock(), NOW, True)
    assert await _notices(session) == []


@pytest.mark.asyncio
async def test_null_last_used_falls_back_to_created(session):
    await _profile(session, last_used=None, created=NOW - timedelta(days=61))
    await profile_reclaim_tick(session, MagicMock(), NOW, True)
    assert len(await _notices(session)) == 1


@pytest.mark.asyncio
async def test_deleted_after_grace_with_audit(session):
    u, t, p = await _profile(session, last_used=NOW - timedelta(days=61))
    rt = MagicMock()
    await profile_reclaim_tick(session, rt, NOW, True)
    await profile_reclaim_tick(session, rt, NOW + timedelta(days=13), True)
    assert await session.get(UserProfile, (u.id, t.id)) is not None
    await profile_reclaim_tick(session, rt, NOW + timedelta(days=14), True)
    assert await session.get(UserProfile, (u.id, t.id)) is None
    rt.remove_volume.assert_called_once_with("profile-v")
    audits = (await session.exec(select(AuditLog).where(AuditLog.action == "profile.reclaim"))).all()
    assert len(audits) == 1 and audits[0].user_id == u.id
    (n,) = await _notices(session)
    assert n.dismissed_at is not None


@pytest.mark.asyncio
async def test_used_after_notice_is_kept_and_dismissed(session):
    u, t, p = await _profile(session, last_used=NOW - timedelta(days=61))
    rt = MagicMock()
    await profile_reclaim_tick(session, rt, NOW, True)
    p.last_used_at = NOW + timedelta(days=5)
    session.add(p)
    await session.commit()
    await profile_reclaim_tick(session, rt, NOW + timedelta(days=15), True)
    assert await session.get(UserProfile, (u.id, t.id)) is not None
    (n,) = await _notices(session)
    assert n.dismissed_at is not None
    rt.remove_volume.assert_not_called()


@pytest.mark.asyncio
async def test_in_use_profile_kept(session):
    u, t, p = await _profile(session, last_used=NOW - timedelta(days=61))
    rt = MagicMock()
    await profile_reclaim_tick(session, rt, NOW, True)
    session.add(Instance(name="i", subdomain="i-sub", template_id=t.id, owner_id=u.id, status="running",
                         profile_volume="profile-v"))
    await session.commit()
    await profile_reclaim_tick(session, rt, NOW + timedelta(days=20), True)
    assert await session.get(UserProfile, (u.id, t.id)) is not None
    rt.remove_volume.assert_not_called()


@pytest.mark.asyncio
async def test_used_after_notice_independent_of_wall_clock(session):
    far = datetime(2030, 1, 1)
    u, t, p = await _profile(session, last_used=far - timedelta(days=61))
    rt = MagicMock()
    await profile_reclaim_tick(session, rt, far, True)
    p.last_used_at = far + timedelta(days=1)
    session.add(p)
    await session.commit()
    await profile_reclaim_tick(session, rt, far + timedelta(days=15), True)
    assert await session.get(UserProfile, (u.id, t.id)) is not None
    rt.remove_volume.assert_not_called()
