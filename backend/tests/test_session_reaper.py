from datetime import datetime, timedelta

from sqlmodel import select

from app.models import Instance, ServiceTemplate, SessionEvent
from app.services import audit_ecs
from app.services.session_reaper import reaper_pass

NOW = datetime(2026, 11, 12, 12, 0, 0)


async def mk(session, started=None, status="running"):
    t = ServiceTemplate(name="d", display_name="D", image="img")
    session.add(t)
    await session.commit()
    i = Instance(template_id=t.id, name="n", subdomain="s", status=status, container_id="c1",
                 started_at=started or NOW - timedelta(hours=1))
    session.add(i)
    await session.commit()
    return i


class Stopper:
    def __init__(self):
        self.stopped = []

    def __call__(self, inst):
        self.stopped.append(inst.id)


def fetcher(state):
    def f(inst):
        if isinstance(state, Exception):
            raise state
        return state
    return f


class Audit(list):
    def __call__(self, ev):
        self.append(ev)


async def run(session, state, stop=None, leader=True, audit=None):
    stop = stop if stop is not None else Stopper()
    audit = audit if audit is not None else Audit()
    n = await reaper_pass(session, stop, fetcher(state), now=NOW, is_leader=lambda: leader,
                          audit=audit)
    return n, stop, audit


async def events(session):
    return [e.event_type for e in (await session.exec(select(SessionEvent))).all()]


async def test_lock_change_records_event_and_audit(session):
    await mk(session)
    _, _, audit = await run(session, {"locked": True, "active_connections": 1})
    assert await events(session) == ["locked"]
    assert audit[0]["event"]["action"] == "session.lock"
    await run(session, {"locked": True, "active_connections": 1}, audit=audit)
    assert await events(session) == ["locked"]  # unchanged: no duplicate
    _, _, audit = await run(session, {"locked": False, "active_connections": 1})
    assert await events(session) == ["locked", "unlocked"]
    assert audit[0]["event"]["action"] == "session.unlock"


async def test_unreachable_gateway_changes_nothing(session):
    inst = await mk(session, started=NOW - timedelta(hours=13))
    n, stop, audit = await run(session, OSError("down"))
    assert n == 0 and not stop.stopped and not audit
    await session.refresh(inst)
    assert inst.status == "running"


async def test_disconnected_over_2h_stopped(session):
    inst = await mk(session)
    ts = (NOW - timedelta(hours=2, minutes=1)).timestamp()
    n, stop, audit = await run(session, {"active_connections": 0, "last_disconnect_ts": ts})
    assert n == 1 and stop.stopped == [inst.id]
    await session.refresh(inst)
    assert inst.status == "stopped"
    assert audit[0]["event"]["action"] == "session.stop"
    assert audit[0]["styx"]["session"]["reason"] == "disconnected"


async def test_disconnected_under_2h_or_connected_kept(session):
    await mk(session)
    ts = (NOW - timedelta(hours=1)).timestamp()
    n, *_ = await run(session, {"active_connections": 0, "last_disconnect_ts": ts})
    old = (NOW - timedelta(hours=5)).timestamp()
    m, *_ = await run(session, {"active_connections": 1, "last_disconnect_ts": old})
    assert n == m == 0


async def test_warning_15min_before_max(session):
    inst = await mk(session, started=NOW - timedelta(hours=11, minutes=50))
    n, stop, _ = await run(session, {"active_connections": 1})
    assert n == 0 and not stop.stopped
    await session.refresh(inst)
    assert inst.notice and "12" in inst.notice
    assert await events(session) == ["max_duration_warned"]


async def test_no_warning_early(session):
    inst = await mk(session, started=NOW - timedelta(hours=11))
    await run(session, {"active_connections": 1})
    await session.refresh(inst)
    assert inst.notice is None


async def test_max_duration_stops(session):
    inst = await mk(session, started=NOW - timedelta(hours=12))
    n, stop, audit = await run(session, {"active_connections": 1})
    assert n == 1 and stop.stopped == [inst.id]
    assert audit[0]["styx"]["session"]["reason"] == "max_duration"


async def test_non_leader_does_nothing(session):
    inst = await mk(session, started=NOW - timedelta(hours=13))
    n, stop, audit = await run(session, {"active_connections": 1}, leader=False)
    assert n == 0 and not stop.stopped and not audit
    await session.refresh(inst)
    assert inst.status == "running"


def test_default_audit_is_ecs_emit():
    from app.services import session_reaper
    assert session_reaper.emit is audit_ecs.emit
