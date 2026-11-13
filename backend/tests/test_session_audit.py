"""record_session_event: SessionEvent row + one ECS styx.audit line (#235)."""
import io
import json
import logging

import pytest
from sqlmodel import select

from app.models import Group, Instance, SessionEvent, User, UserGroup
from app.services.session_audit import record_session_event


@pytest.fixture
def lines():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("styx.audit")
    log.addHandler(h)
    yield lambda: [json.loads(ln) for ln in buf.getvalue().splitlines() if ln]
    log.removeHandler(h)


async def _inst(session, digest="sha256:abc"):
    user = User(username="ann", email="ann@example.com", password_hash="x")
    session.add(user)
    grp = Group(name="devs")
    session.add(grp)
    await session.flush()
    session.add(UserGroup(user_id=user.id, group_id=grp.id))
    inst = Instance(owner_id=user.id, template_id="t", name="i1", subdomain="s1", image_digest=digest)
    session.add(inst)
    await session.commit()
    return user, inst


@pytest.mark.asyncio
async def test_row_and_ecs_line(session, lines, monkeypatch):
    monkeypatch.setenv("NODE_NAME", "node-1")
    user, inst = await _inst(session)
    await record_session_event(session, inst, "stopped", action="session.stop", reason="user")
    await session.commit()
    rows = (await session.exec(select(SessionEvent))).all()
    assert [(r.instance_id, r.event_type) for r in rows] == [(inst.id, "stopped")]
    (ev,) = lines()
    assert ev["event"]["action"] == "session.stop"
    assert ev["event"]["type"] == ["end"]
    s = ev["styx"]["session"]
    assert (s["id"], s["kind"], s["reason"], s["groups"]) == (inst.id, "instance", "user", ["devs"])
    assert ev["user"] == {"id": user.id, "name": "ann"}
    assert ev["host"]["name"] == "node-1"
    assert ev["container"]["image"]["hash"]["all"] == ["sha256:abc"]


@pytest.mark.asyncio
async def test_no_action_no_line(session, lines):
    _, inst = await _inst(session)
    await record_session_event(session, inst, "restarted", details={"k": 1})
    await session.commit()
    row = (await session.exec(select(SessionEvent))).one()
    assert row.details == {"k": 1}
    assert lines() == []


@pytest.mark.asyncio
async def test_node_falls_back_to_hostname(session, lines, monkeypatch):
    monkeypatch.delenv("NODE_NAME", raising=False)
    monkeypatch.setattr("socket.gethostname", lambda: "box")
    _, inst = await _inst(session)
    await record_session_event(session, inst, "paused", action="session.lock")
    assert lines()[0]["host"]["name"] == "box"
