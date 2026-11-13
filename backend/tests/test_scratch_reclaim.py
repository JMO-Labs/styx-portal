from datetime import datetime, timedelta
from unittest.mock import MagicMock

from sqlmodel import select

from app.models import AuditLog, Instance, Notice, ServiceTemplate, User
from app.services.scratch_reclaim import scratch_reclaim_tick

NOW = datetime(2026, 11, 13, 12, 0)


async def _inst(session, name, *, status="stopped", age_days=8, vols=("s1", "s2")):
    u = (await session.exec(select(User).where(User.username == "sr"))).first()
    if not u:
        u = User(username="sr", password_hash="x", role="user")
        t = ServiceTemplate(name="t", display_name="T", image="i")
        session.add_all([u, t])
        await session.commit()
    t = (await session.exec(select(ServiceTemplate))).first()
    i = Instance(template_id=t.id, owner_id=u.id, name=name, subdomain=name, status=status,
                 stopped_at=NOW - timedelta(days=age_days), volume_names=list(vols),
                 profile_volume="prof")
    session.add(i)
    await session.commit()
    return i


async def test_noop_when_not_leader(session):
    i = await _inst(session, "a")
    rt = MagicMock()
    assert await scratch_reclaim_tick(session, rt, NOW, False) == 0
    rt.remove_volume.assert_not_called()
    await session.refresh(i)
    assert i.volume_names == ["s1", "s2"]


async def test_reclaims_old_stopped_only(session):
    old = await _inst(session, "old")
    new = await _inst(session, "new", age_days=6, vols=("n1",))
    run = await _inst(session, "run", status="running", vols=("r1",))
    rt = MagicMock()
    assert await scratch_reclaim_tick(session, rt, NOW, True) == 1
    assert [c.args[0] for c in rt.remove_volume.call_args_list] == ["s1", "s2"]
    for x in (old, new, run):
        await session.refresh(x)
    assert old.volume_names == [] and old.profile_volume == "prof"
    assert new.volume_names == ["n1"] and run.volume_names == ["r1"]


async def test_notice_audit_once(session):
    i = await _inst(session, "a")
    rt = MagicMock()
    await scratch_reclaim_tick(session, rt, NOW, True)
    await scratch_reclaim_tick(session, rt, NOW, True)
    n = (await session.exec(select(Notice))).all()
    assert len(n) == 1 and n[0].kind == "scratch_reclaim" and n[0].key == i.id
    assert "home" in n[0].message and "profile" in n[0].message
    a = (await session.exec(select(AuditLog).where(AuditLog.action == "scratch_reclaim"))).all()
    assert len(a) == 1 and a[0].resource == i.id
    assert rt.remove_volume.call_count == 2


async def test_missing_volume_is_ok(session):
    i = await _inst(session, "a", vols=("gone",))
    rt = MagicMock()
    rt.remove_volume.side_effect = type("NotFound", (Exception,), {})()
    await scratch_reclaim_tick(session, rt, NOW, True)
    await session.refresh(i)
    assert i.volume_names == []
