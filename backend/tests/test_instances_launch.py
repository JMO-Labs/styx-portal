"""Background launch failure path: instance goes to error and an event is stored."""
from unittest.mock import MagicMock, patch

import pytest
from sqlmodel import select

from app.models import Instance, ServiceTemplate, SessionEvent
from app.routers.instances import _launch_instance_background


class _Ctx:
    def __init__(self, session):
        self._s = session

    async def __aenter__(self):
        return self._s

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_launch_failure_marks_error_and_logs_event(session):
    tmpl = ServiceTemplate(
        name="boom-tmpl", display_name="Boom", image="test:latest", internal_port=3001,
    )
    session.add(tmpl)
    await session.commit()
    inst = Instance(
        template_id=tmpl.id, name="boom", subdomain="boom", status="starting", volume_names=[],
    )
    session.add(inst)
    await session.commit()
    instance_id = inst.id

    docker = MagicMock()
    docker.image_exists.return_value = True
    docker.create_volume.side_effect = lambda name, size=None: name
    docker.create_container.side_effect = RuntimeError("boom")

    with patch("app.routers.instances.instance_runtime", return_value=docker), \
         patch("app.routers.instances.async_session", lambda: _Ctx(session)):
        await _launch_instance_background(instance_id, tmpl.id)

    session.expire_all()
    got = await session.get(Instance, instance_id)
    assert got.status == "error"
    assert got.error_message == "boom"
    events = (await session.exec(
        select(SessionEvent).where(SessionEvent.instance_id == instance_id)
    )).all()
    assert [(e.event_type, e.details) for e in events] == [("error", {"error": "boom"})]
