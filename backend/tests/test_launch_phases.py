import logging

import httpx

from tests.test_k8s_instances import DEP, PODS, Rec, _create

READY = {"metadata": {"generation": 1}, "spec": {"replicas": 1},
         "status": {"observedGeneration": 1, "updatedReplicas": 1, "readyReplicas": 1}}


def _rt():
    return Rec({("GET", DEP): httpx.Response(200, json=READY),
                ("GET", PODS): httpx.Response(200, json={"items": []})}).runtime()


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
