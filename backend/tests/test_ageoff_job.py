import os
from datetime import datetime, timedelta

import pytest
from sqlmodel import select

from app.models import AuditLog, Notice, User
from app.services.ageoff_job import ageoff_tick

NOW = datetime(2026, 11, 13, 3, 0)


class FakeStore:
    def __init__(self, fail=False):
        self.puts, self.fail = [], fail

    def put(self, uid, rel, fileobj, mtime):
        if self.fail:
            raise OSError("boom")
        self.puts.append((uid, rel, fileobj.read()))


async def _setup(session, tmp_path):
    u = User(username="a1", password_hash="x", role="user")
    session.add(u)
    await session.commit()
    home = tmp_path / u.id
    home.mkdir()
    f = home / "old.txt"
    f.write_text("hi")
    old = (NOW - timedelta(days=200)).timestamp()
    os.utime(f, (old, old))
    return u, f


async def _run(session, store, tmp_path, now, leader=True, dry=False):
    return await ageoff_tick(session, store, now, lambda: leader, dry,
                             homes_root=str(tmp_path))


async def _age_notice(session, days):
    n = (await session.exec(select(Notice))).one()
    n.created_at = n.created_at - timedelta(days=days)
    session.add(n)
    await session.commit()


@pytest.mark.asyncio
async def test_not_leader_noop(session, tmp_path):
    await _setup(session, tmp_path)
    st = FakeStore()
    assert await _run(session, st, tmp_path, NOW, leader=False) == {}
    assert (await session.exec(select(Notice))).all() == []


@pytest.mark.asyncio
async def test_notice_once_per_day_no_upload(session, tmp_path):
    u, f = await _setup(session, tmp_path)
    st = FakeStore()
    await _run(session, st, tmp_path, NOW)
    await _run(session, st, tmp_path, NOW)
    ns = (await session.exec(select(Notice))).all()
    assert len(ns) == 1 and ns[0].kind == "ageoff" and ns[0].user_id == u.id
    assert st.puts == [] and f.exists()


@pytest.mark.asyncio
async def test_move_after_notice_period(session, tmp_path):
    u, f = await _setup(session, tmp_path)
    st = FakeStore()
    await _run(session, st, tmp_path, NOW)
    await _age_notice(session, 15)
    await _run(session, st, tmp_path, NOW)
    assert st.puts == [(u.id, "old.txt", b"hi")] and not f.exists()
    audits = (await session.exec(select(AuditLog).where(AuditLog.action == "ageoff.move"))).all()
    assert len(audits) == 1 and audits[0].user_id == u.id
    await _run(session, st, tmp_path, NOW)
    assert len(st.puts) == 1


@pytest.mark.asyncio
async def test_upload_error_keeps_file(session, tmp_path):
    u, f = await _setup(session, tmp_path)
    await _run(session, FakeStore(), tmp_path, NOW)
    await _age_notice(session, 15)
    await _run(session, FakeStore(fail=True), tmp_path, NOW)
    assert f.exists()


@pytest.mark.asyncio
async def test_dry_run_changes_nothing(session, tmp_path):
    u, f = await _setup(session, tmp_path)
    st = FakeStore()
    await _run(session, st, tmp_path, NOW)
    await _age_notice(session, 15)
    res = await _run(session, st, tmp_path, NOW, dry=True)
    assert res[u.id].action == "move" and res[u.id].files == ["old.txt"]
    assert st.puts == [] and f.exists()
    assert (await session.exec(select(AuditLog))).all() == []
