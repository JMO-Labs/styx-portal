"""Create path: _launch_instance_background records launch SLI metrics (#250)."""
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from prometheus_client import REGISTRY
from sqlmodel import select

from app.models import Instance, ServiceTemplate, User
from app.routers import instances as r
from app.security.passwords import hash_password

DUR = "styx_launch_duration_seconds_count"
FAIL = "styx_launch_failures_total"


def _dur(outcome: str) -> float:
    return REGISTRY.get_sample_value(DUR, {"kind": "create", "outcome": outcome}) or 0.0


def _fail() -> float:
    return REGISTRY.get_sample_value(FAIL, {"reason": "other"}) or 0.0


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
    m.image_exists.return_value = True
    m.create_container.return_value = "cid"
    m.get_image_info.return_value = {"size_mb": 1}
    if start_exc:
        m.start_container.side_effect = start_exc

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            pass

    with patch.object(r, "instance_runtime", return_value=m), \
         patch.object(r, "async_session", lambda: Ctx()), \
         patch.object(r.profiles, "prepare_volumes", AsyncMock(return_value={})), \
         patch.object(r, "launch_overrides", AsyncMock(return_value=({}, None, None))), \
         patch.object(r.gpu_access, "resolve_gpu", AsyncMock(return_value=False)), \
         patch.object(r, "_home_kwargs", AsyncMock(return_value={})), \
         patch.object(r, "_egress_kwargs", AsyncMock(return_value={})), \
         patch.object(r, "_isolate_or_409", AsyncMock()), \
         patch.object(r, "_pinned", return_value=None), \
         patch.object(r, "_refresh_routes", AsyncMock()):
        await r._launch_instance_background(iid, tid, time.monotonic())


@pytest.mark.asyncio
async def test_create_ok_observes_duration(session, monkeypatch):
    monkeypatch.setenv("ROUTE_BACKEND", "file")
    iid, tid = await _setup(session)
    ok, err, f = _dur("ok"), _dur("error"), _fail()
    await _run(session, iid, tid)
    assert _dur("ok") == ok + 1
    assert _dur("error") == err
    assert _fail() == f


@pytest.mark.asyncio
async def test_create_failure_counts_and_sets_error(session, monkeypatch):
    monkeypatch.setenv("ROUTE_BACKEND", "file")
    iid, tid = await _setup(session)
    ok, err, f = _dur("ok"), _dur("error"), _fail()
    await _run(session, iid, tid, start_exc=RuntimeError("boom"))
    assert _dur("error") == err + 1
    assert _fail() == f + 1
    assert _dur("ok") == ok
    inst = (await session.exec(select(Instance).where(Instance.id == iid))).one()
    await session.refresh(inst)
    assert inst.status == "error"
