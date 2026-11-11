from unittest.mock import MagicMock, patch

from prometheus_client import REGISTRY

from app.models import Instance
from app.routers.instances import _launch_instance_background
from tests.test_gpu_access import _mk

DUR = "styx_instance_launch_duration_seconds_count"
FAIL = "styx_instance_launch_failures_total"


def _v(name):
    return REGISTRY.get_sample_value(name) or 0.0


async def _run(session, tid, start_error=None):
    inst = Instance(template_id=tid, name="m1", subdomain="m1", status="starting")
    session.add(inst)
    await session.commit()
    await session.refresh(inst)
    mgr = MagicMock()
    mgr.create_volume.side_effect = lambda name, size=None: name
    mgr.create_container.return_value = "c1"
    mgr.image_exists.return_value = True
    mgr.get_image_info.return_value = {"size_mb": 1}
    mgr.start_container.side_effect = start_error

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            pass

    with patch("app.routers.instances.instance_runtime", return_value=mgr), \
            patch("app.routers.instances.async_session", lambda: Ctx()):
        await _launch_instance_background(inst.id, tid)
    await session.refresh(inst)
    return inst


async def test_success_observes_duration(admin_client, session):
    tid = await _mk(admin_client)
    d, f = _v(DUR), _v(FAIL)
    inst = await _run(session, tid)
    assert inst.status == "running"
    assert _v(DUR) == d + 1
    assert _v(FAIL) == f


async def test_failure_counts_not_duration(admin_client, session):
    tid = await _mk(admin_client)
    d, f = _v(DUR), _v(FAIL)
    inst = await _run(session, tid, RuntimeError("boom"))
    assert inst.status == "error"
    assert _v(FAIL) == f + 1
    assert _v(DUR) == d
