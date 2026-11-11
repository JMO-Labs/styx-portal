import time
from unittest.mock import patch

import pytest
from prometheus_client import REGISTRY

from app.services import instance_readiness as ir
from tests.test_instance_readiness import _inst, _wait

N = "styx_launch_duration_seconds_count"


def _c(kind, outcome):
    return REGISTRY.get_sample_value(N, {"kind": kind, "outcome": outcome}) or 0.0


@pytest.mark.asyncio
async def test_ready_observes_ok_with_requested_at(session):
    i = await _inst(session)
    before = _c("create", "ok")
    await _wait(session, [{"status": "running"}], iid=i.id,
                requested_at=time.monotonic() - 7, kind="create")
    assert _c("create", "ok") == before + 1
    assert REGISTRY.get_sample_value("styx_launch_duration_seconds_bucket",
                                     {"kind": "create", "outcome": "ok", "le": "5.0"}) is not None


@pytest.mark.asyncio
async def test_timeout_observes_timeout(session):
    i = await _inst(session)
    before = _c("start", "timeout")
    await _wait(session, [{"status": "created", "detail": "Starting"}] * 5, iid=i.id,
                timeout=-1, requested_at=time.monotonic(), kind="start")
    assert _c("start", "timeout") == before + 1


@pytest.mark.asyncio
async def test_fatal_observes_error(session):
    i = await _inst(session)
    before = _c("resume", "error")
    with patch.object(ir, "FATAL_GRACE", -1):
        await _wait(session, [{"status": "created", "detail": "ImagePullBackOff"}] * 3,
                    iid=i.id, requested_at=time.monotonic(), kind="resume")
    assert _c("resume", "error") == before + 1


@pytest.mark.asyncio
async def test_no_requested_at_observes_nothing(session):
    i = await _inst(session)
    before = _c("start", "ok")
    await _wait(session, [{"status": "running"}], iid=i.id)
    assert _c("start", "ok") == before


@pytest.mark.asyncio
async def test_docker_start_path_observes_launch(admin_client, session, monkeypatch):
    from tests.test_instances_api import _make_owned_instance
    monkeypatch.setenv("ROUTE_BACKEND", "file")
    inst = await _make_owned_instance(session, status="stopped")
    before = _c("start", "ok")
    r = await admin_client.post(f"/api/instances/{inst.id}/start")
    assert r.status_code == 200, r.text
    assert _c("start", "ok") == before + 1
