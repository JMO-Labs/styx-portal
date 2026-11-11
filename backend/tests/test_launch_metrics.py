"""Launch duration/failure metrics in _launch_instance_background."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY
from sqlmodel import select

from app.models import Instance, ServiceTemplate, User
from app.routers.instances import _launch_instance_background
from app.security.passwords import hash_password

DUR = "styx_instance_launch_duration_seconds_count"
FAIL = "styx_instance_launch_failures_total"


def _val(name: str) -> float:
    return REGISTRY.get_sample_value(name) or 0.0


async def _setup(session):
    user = User(username="lm", password_hash=hash_password("x"), role="admin", is_active=True)
    tmpl = ServiceTemplate(name="lm-t", display_name="LM", image="t:latest", internal_port=3001)
    session.add(user)
    session.add(tmpl)
    await session.commit()
    inst = Instance(template_id=tmpl.id, owner_id=user.id, name="lm", subdomain="lm",
                    status="starting", volume_names=[])
    session.add(inst)
    await session.commit()
    return inst.id, tmpl.id


async def _run(session, iid, tid, start_exc=None):
    m = MagicMock()
    m.create_volume.side_effect = lambda name, size=None: name
    m.create_container.return_value = "cid"
    m.image_exists.return_value = True
    m.pull_image_streaming = AsyncMock()
    m.get_image_info.return_value = {"size_mb": 1}
    if start_exc:
        m.start_container.side_effect = start_exc

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            pass

    with patch("app.routers.instances.instance_runtime", return_value=m), \
         patch("app.routers.instances.async_session", lambda: Ctx()):
        await _launch_instance_background(iid, tid)


@pytest.mark.asyncio
async def test_success_observes_duration(session):
    iid, tid = await _setup(session)
    d, f = _val(DUR), _val(FAIL)
    await _run(session, iid, tid)
    assert _val(DUR) == d + 1
    assert _val(FAIL) == f


@pytest.mark.asyncio
async def test_failure_counts_and_sets_error(session):
    iid, tid = await _setup(session)
    d, f = _val(DUR), _val(FAIL)
    await _run(session, iid, tid, start_exc=RuntimeError("boom"))
    assert _val(FAIL) == f + 1
    assert _val(DUR) == d
    inst = (await session.exec(select(Instance).where(Instance.id == iid))).one()
    await session.refresh(inst)
    assert inst.status == "error"
