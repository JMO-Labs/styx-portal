from datetime import datetime, timedelta

import httpx
from sqlmodel import select

from app.config import Settings
from app.models import Instance, ServiceTemplate, SessionEvent
from app.services import cve_recycle
from app.services.cve_recycle import recycle_pass

NOW = datetime(2026, 11, 12, 12, 0, 0)
IMG = "harbor.example/styx/desktop:latest"


def cfg():
    return Settings(HARBOR_URL="https://harbor.example", HARBOR_USER="u", HARBOR_PASSWORD="p")


def harbor(severities):
    calls = []

    def h(r):
        calls.append(r)
        vulns = [{"severity": s} for s in severities]
        return httpx.Response(200, json={"application/vnd.security.vulnerability.report; "
                                         "version=1.1": {"vulnerabilities": vulns}})
    return httpx.Client(transport=httpx.MockTransport(h)), calls


async def mk(session, digest="sha256:abc", status="running"):
    t = ServiceTemplate(name="d", display_name="D", image=IMG)
    session.add(t)
    await session.commit()
    i = Instance(template_id=t.id, name="n", subdomain="s", status=status, image_digest=digest)
    session.add(i)
    await session.commit()
    return i


class Stopper:
    def __init__(self):
        self.stopped = []

    def __call__(self, inst):
        self.stopped.append(inst.id)


async def run(session, client, stop, now=NOW, leader=True):
    return await recycle_pass(session, stop, cfg(), client, now=now, is_leader=lambda: leader)


async def test_critical_warns_once_and_sets_deadline(session):
    inst = await mk(session)
    client, calls = harbor(["Critical", "Low"])
    stop = Stopper()
    await run(session, client, stop)
    await session.refresh(inst)
    assert inst.recycle_deadline == NOW + timedelta(hours=24)
    assert inst.notice and "24" in inst.notice
    assert "/artifacts/sha256:abc/additions/vulnerabilities" in calls[0].url.raw_path.decode()
    await run(session, client, stop, now=NOW + timedelta(hours=1))
    await session.refresh(inst)
    assert inst.recycle_deadline == NOW + timedelta(hours=24)  # unchanged
    assert stop.stopped == []
    events = (await session.exec(
        select(SessionEvent).where(SessionEvent.event_type == "cve_warned"))).all()
    assert len(events) == 1


async def test_stops_after_deadline(session):
    inst = await mk(session)
    client, _ = harbor(["CRITICAL"])
    stop = Stopper()
    await run(session, client, stop)
    await run(session, client, stop, now=NOW + timedelta(hours=24, seconds=1))
    await session.refresh(inst)
    assert stop.stopped == [inst.id]
    assert inst.status == "stopped"


async def test_high_only_does_nothing(session):
    inst = await mk(session)
    client, _ = harbor(["High", "Medium"])
    stop = Stopper()
    await run(session, client, stop, now=NOW + timedelta(days=3))
    await session.refresh(inst)
    assert inst.recycle_deadline is None and inst.notice is None
    assert stop.stopped == [] and inst.status == "running"


async def test_non_leader_does_nothing(session):
    inst = await mk(session)
    client, calls = harbor(["Critical"])
    await run(session, client, Stopper(), leader=False)
    await session.refresh(inst)
    assert calls == [] and inst.recycle_deadline is None


async def test_harbor_down_keeps_state(session):
    inst = await mk(session)
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    stop = Stopper()
    await run(session, client, stop)
    await session.refresh(inst)
    assert inst.recycle_deadline is None and stop.stopped == []


async def test_no_digest_or_no_harbor_skipped(session):
    await mk(session, digest=None)
    client, calls = harbor(["Critical"])
    await run(session, client, Stopper())
    assert calls == []
    assert await cve_recycle.recycle_pass(
        session, Stopper(), Settings(HARBOR_URL=""), client, now=NOW, is_leader=lambda: True) == 0
