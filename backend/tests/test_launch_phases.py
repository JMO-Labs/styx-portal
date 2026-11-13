import logging

import httpx
import pytest

from app.services import k8s_instances
from tests.test_k8s_instances import DEP, PODS, Rec, _create

READY = {"metadata": {"generation": 1}, "spec": {"replicas": 1},
         "status": {"observedGeneration": 1, "updatedReplicas": 1, "readyReplicas": 1}}


@pytest.fixture(autouse=True)
def _clear_launches():
    k8s_instances._LAUNCHES.clear()
    yield
    k8s_instances._LAUNCHES.clear()


def _rec():
    return Rec({("GET", DEP): httpx.Response(200, json=READY),
                ("GET", PODS): httpx.Response(200, json={"items": []})})


def _rt():
    return _rec().runtime()


def _lines(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("launch_phases")]


def test_one_launch_phases_line_with_durations(caplog):
    caplog.set_level(logging.INFO, logger="styx-portal")
    rt = _rt()
    _create(rt, image="harbor.secret/proj/myimage:1")
    rt.start_container("selkies-a")
    assert _lines(caplog) == []
    rt.get_container_status("selkies-a")
    rt.get_container_status("selkies-a")  # later polls must not log again
    lines = _lines(caplog)
    assert len(lines) == 1
    for key in ("digest_s=", "apply_s=", "ready_s=", "total_s="):
        assert key in lines[0]
    assert "selkies-a" not in lines[0] and "myimage" not in lines[0] and "u1" not in lines[0]


def test_no_line_without_launch(caplog):
    caplog.set_level(logging.INFO, logger="styx-portal")
    _rt().get_container_status("selkies-a")
    assert _lines(caplog) == []


def test_logs_when_status_polled_on_fresh_runtime(caplog):
    """instance_runtime() builds a new runtime per call; readiness polls a fresh one."""
    caplog.set_level(logging.INFO, logger="styx-portal")
    rec = _rec()
    launcher = rec.runtime()
    _create(launcher)
    launcher.start_container("selkies-a")
    poller = rec.runtime()
    poller.get_container_status("selkies-a")
    rec.runtime().get_container_status("selkies-a")
    assert len(_lines(caplog)) == 1


def test_remove_evicts_pending_launch(caplog):
    caplog.set_level(logging.INFO, logger="styx-portal")
    rec = _rec()
    rt = rec.runtime()
    _create(rt)
    rt.start_container("selkies-a")
    rec.runtime().remove_container("selkies-a")
    assert "selkies-a" not in k8s_instances._LAUNCHES
    rt.get_container_status("selkies-a")
    assert _lines(caplog) == []


def test_stale_entries_pruned():
    rt = _rt()
    _create(rt)
    k8s_instances._LAUNCHES["selkies-a"]["t0"] -= k8s_instances._LAUNCH_TTL_S + 1
    _create(rt, name="selkies-b")
    assert "selkies-a" not in k8s_instances._LAUNCHES
    assert "selkies-b" in k8s_instances._LAUNCHES
