"""record_session_event: SessionEvent row + one ECS styx.audit line (#235)."""
import io
import json
import logging

import pytest
from sqlmodel import select

from app.models import Group, Instance, ServiceTemplate, SessionEvent, User, UserGroup
from app.services.session_audit import record_session_event
from tests.test_instances_api import (  # noqa: F401  fixtures
    _make_owned_instance,
    shared_docker,
    template_id,
)


@pytest.fixture
def lines():
    buf = io.StringIO()
    h = logging.StreamHandler(buf)
    h.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("styx.audit")
    log.addHandler(h)
    yield lambda: [json.loads(ln) for ln in buf.getvalue().splitlines() if ln]
    log.removeHandler(h)


def _session_only(evs):
    """Drop non-session audit lines (e.g. instance.create/delete)."""
    return [e for e in evs if e["event"]["action"].startswith("session.")]


async def _inst(session, digest="sha256:abc"):
    user = User(username="ann", email="ann@example.com", password_hash="x")
    session.add(user)
    grp = Group(name="devs")
    tmpl = ServiceTemplate(name="t", display_name="t", image="x:latest")
    session.add_all([grp, tmpl])
    await session.flush()
    session.add(UserGroup(user_id=user.id, group_id=grp.id))
    inst = Instance(owner_id=user.id, template_id=tmpl.id, name="i1", subdomain="s1", image_digest=digest)
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


# --- router wiring (#235 AC 2) ---

@pytest.mark.parametrize(
    "status,verb,action,reason",
    [
        ("stopped", "start", "session.launch", None),
        ("running", "stop", "session.stop", "user"),
        ("running", "pause", "session.lock", None),
        ("paused", "unpause", "session.unlock", None),
        ("running", "delete", "session.stop", "deleted"),
    ],
)
@pytest.mark.usefixtures("shared_docker")
@pytest.mark.asyncio
async def test_router_emits_session_line(admin_client, session, lines,
                                         status, verb, action, reason):
    inst = await _make_owned_instance(session, status=status)
    iid = inst.id
    url = f"/api/instances/{iid}"
    if verb == "delete":
        resp = await admin_client.delete(url)
        assert resp.status_code == 204
    else:
        resp = await admin_client.post(f"{url}/{verb}")
        assert resp.status_code == 200, resp.text
    (ev,) = _session_only(lines())
    assert ev["event"]["action"] == action
    assert ev["styx"]["session"]["id"] == iid
    assert ev["styx"]["session"].get("reason") == reason


@pytest.mark.asyncio
async def test_background_launch_emits_session_launch(session, lines):
    from unittest.mock import patch

    from app.routers.instances import _launch_instance_background
    from tests.test_instance_image_digest import runtime

    tmpl = ServiceTemplate(name="sl", display_name="sl", image="x:latest")
    user = User(username="sl", password_hash="x", role="admin", is_active=True)
    session.add_all([tmpl, user])
    await session.commit()
    inst = Instance(template_id=tmpl.id, owner_id=user.id, name="sl", subdomain="sl",
                    status="starting", volume_names=[])
    session.add(inst)
    await session.commit()

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            return False

    with patch("app.routers.instances.instance_runtime", return_value=runtime(None)), \
         patch("app.routers.instances.async_session", lambda: Ctx()):
        await _launch_instance_background(inst.id, tmpl.id)
    (ev,) = _session_only(lines())
    assert ev["event"]["action"] == "session.launch"
    assert ev["styx"]["session"]["id"] == inst.id


@pytest.mark.usefixtures("shared_docker")
@pytest.mark.asyncio
async def test_router_restart_emits_no_line(admin_client, session, lines):
    inst = await _make_owned_instance(session, status="running")
    resp = await admin_client.post(f"/api/instances/{inst.id}/restart")
    assert resp.status_code == 200, resp.text
    assert lines() == []
