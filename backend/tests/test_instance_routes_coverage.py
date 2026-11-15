"""Coverage for instance_info / instance_ops / instance_build / instance_deps (#353)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from sqlmodel import select

from app.main import app
from app.models import Instance, PulledImage, ServiceTemplate, SessionEvent, User
from app.routers.instances import get_docker_manager, get_screenshot_service

TMPL = {"name": "cov-tmpl", "display_name": "Cov", "image": "cov:latest", "internal_port": 3001}


@pytest.fixture
def docker():
    m = MagicMock()
    m.get_container_status.return_value = {"status": "running"}
    m.instance_usage.return_value = {"cpu_percent": 1}
    m.instance_logs.return_value = ["a", "b"]
    app.dependency_overrides[get_docker_manager] = lambda: m
    return m


@pytest.fixture
async def tmpl_id(admin_client):
    return (await admin_client.post("/api/templates", json=TMPL)).json()["id"]


async def _inst(session, tmpl_id, owner="admin", **kw):
    if owner == "admin":
        owner = (await session.exec(select(User).where(User.username == "admin"))).first().id
    kw.setdefault("status", "running")
    kw.setdefault("container_id", "cid")
    i = Instance(template_id=tmpl_id, owner_id=owner, name="n", subdomain=f"s{id(kw)}", **kw)
    session.add(i)
    await session.commit()
    await session.refresh(i)
    return i


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", [
    ("get", "status"), ("get", "stats"), ("post", "keepalive"), ("patch", ""),
    ("patch", "session"), ("get", "screenshot"), ("post", "screenshot/refresh"),
    ("get", "events"), ("get", "logs"), ("post", "pause"), ("post", "unpause"),
    ("delete", ""),
])
async def test_missing_instance_404(admin_client, docker, method, path):
    kw = {"json": {}} if method == "patch" else {}
    r = await admin_client.request(method, f"/api/instances/nope/{path}".rstrip("/"), **kw)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_status_uptime_idle_and_pull_progress(admin_client, session, docker, tmpl_id):
    from app.services import pull_progress
    now = datetime.now(timezone.utc)
    i = await _inst(session, tmpl_id, started_at=now - timedelta(seconds=100),
                    last_activity=now - timedelta(seconds=10))
    pull_progress.set_progress(i.id, 42, "layer x")
    d = (await admin_client.get(f"/api/instances/{i.id}/status")).json()
    assert d["uptime_seconds"] >= 99 and d["idle_seconds"] >= 9
    assert d["pull_percent"] == 42 and d["pull_detail"] == "layer x"
    assert d["status"] == "running"


@pytest.mark.asyncio
async def test_stats_zero_when_stopped_and_usage_when_running(admin_client, session, docker, tmpl_id):
    s = await _inst(session, tmpl_id, status="stopped")
    assert (await admin_client.get(f"/api/instances/{s.id}/stats")).json()["memory_mb"] == 0
    r = await _inst(session, tmpl_id)
    assert (await admin_client.get(f"/api/instances/{r.id}/stats")).json() == {"cpu_percent": 1}


@pytest.mark.asyncio
async def test_keepalive_wakes_idle(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id, status="idle")
    d = (await admin_client.post(f"/api/instances/{i.id}/keepalive")).json()
    assert d["status"] == "running"


@pytest.mark.asyncio
async def test_update_and_session_patch(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id)
    r = await admin_client.patch(f"/api/instances/{i.id}", json={"name": "renamed"})
    assert r.json()["name"] == "renamed"
    r = await admin_client.patch(f"/api/instances/{i.id}/session", json={"idle_timeout": "5m"})
    assert r.status_code == 200 and r.json()["session_config"]["idle_timeout"] == "5m"


@pytest.mark.asyncio
async def test_screenshot_missing_and_present(admin_client, session, docker, tmpl_id, tmp_path):
    i = await _inst(session, tmpl_id)
    svc = MagicMock()
    svc.get_path.return_value = None
    app.dependency_overrides[get_screenshot_service] = lambda: svc
    assert (await admin_client.get(f"/api/instances/{i.id}/screenshot")).status_code == 404
    png = tmp_path / "s.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 16)
    svc.get_path.return_value = png
    r = await admin_client.get(f"/api/instances/{i.id}/screenshot")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_screenshot_refresh_branches(admin_client, session, docker, tmpl_id, monkeypatch):
    stopped = await _inst(session, tmpl_id, status="stopped")
    r = await admin_client.post(f"/api/instances/{stopped.id}/screenshot/refresh")
    assert r.json() == {"ok": False, "reason": "not running"}
    run = await _inst(session, tmpl_id)
    assert (await admin_client.post(f"/api/instances/{run.id}/screenshot/refresh")).json() == {"ok": True}
    monkeypatch.setenv("ROUTE_BACKEND", "k8s")
    r = await admin_client.post(f"/api/instances/{run.id}/screenshot/refresh")
    assert r.json()["ok"] is False and "Kubernetes" in r.json()["reason"]


@pytest.mark.asyncio
async def test_events_and_logs(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id)
    session.add(SessionEvent(instance_id=i.id, event_type="crash", details={"error": "boom"}))
    session.add(SessionEvent(instance_id=i.id, event_type="paused"))
    await session.commit()
    ev = (await admin_client.get(f"/api/instances/{i.id}/events")).json()
    assert {e["type"]: e["details"] for e in ev} == {"crash": "boom", "paused": None}
    assert (await admin_client.get(f"/api/instances/{i.id}/logs")).json() == ["a", "b"]
    docker.instance_logs.side_effect = RuntimeError("x")
    assert (await admin_client.get(f"/api/instances/{i.id}/logs")).json() == []
    bare = await _inst(session, tmpl_id, container_id=None)
    assert (await admin_client.get(f"/api/instances/{bare.id}/logs")).json() == []


@pytest.mark.asyncio
async def test_pause_unpause_flow_and_conflicts(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id)
    assert (await admin_client.post(f"/api/instances/{i.id}/unpause")).status_code == 409
    r = await admin_client.post(f"/api/instances/{i.id}/pause")
    assert r.json()["status"] == "paused"
    assert (await admin_client.post(f"/api/instances/{i.id}/pause")).status_code == 409
    r = await admin_client.post(f"/api/instances/{i.id}/unpause")
    assert r.json()["status"] == "running"
    docker.pause_container.assert_called_once_with("cid")
    docker.unpause_container.assert_called_once_with("cid")


@pytest.mark.asyncio
async def test_delete_full_cleanup(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id, volume_names=["v1", "v2"])
    session.add(PulledImage(image="cov:latest"))
    await session.commit()
    docker.remove_volume.side_effect = [RuntimeError("gone"), None]
    r = await admin_client.delete(
        f"/api/instances/{i.id}?remove_image=true&remove_template=true")
    assert r.status_code == 204
    docker.remove_container.assert_called_once_with("cid")
    docker.remove_image.assert_called_once_with("cov:latest")
    docker.remove_user_network.assert_called_once()
    assert await session.get(ServiceTemplate, tmpl_id) is None
    assert (await session.exec(select(PulledImage))).first() is None


@pytest.mark.asyncio
async def test_delete_skips_missing_container_and_image_errors(admin_client, session, docker, tmpl_id):
    i = await _inst(session, tmpl_id)
    session.add(PulledImage(image="cov:latest"))
    await session.commit()
    docker.get_container_status.return_value = {"status": "not_found"}
    docker.remove_image.side_effect = RuntimeError("in use")
    r = await admin_client.delete(f"/api/instances/{i.id}?remove_image=true")
    assert r.status_code == 204
    docker.remove_container.assert_not_called()


@pytest.mark.asyncio
async def test_delete_keeps_image_and_template_when_shared(admin_client, session, docker, tmpl_id):
    a = await _inst(session, tmpl_id)
    await _inst(session, tmpl_id)
    r = await admin_client.delete(
        f"/api/instances/{a.id}?remove_image=true&remove_template=true")
    assert r.status_code == 204
    docker.remove_image.assert_not_called()
    assert await session.get(ServiceTemplate, tmpl_id) is not None
    docker.remove_user_network.assert_not_called()


@pytest.mark.asyncio
async def test_build_removes_container_when_isolation_fails(session, tmpl_id=None):
    from app.services.instance_build import _build_and_start_container
    docker = MagicMock()
    docker.create_container.return_value = "cid2"
    docker.ensure_isolated.side_effect = RuntimeError("net")
    tmpl = ServiceTemplate(name="t", display_name="T", image="i:1", internal_port=3001)
    inst = Instance(template_id="t", owner_id="u1", name="n", subdomain="sub")
    with pytest.raises(HTTPException) as e:
        await _build_and_start_container(inst, tmpl, docker, session)
    assert e.value.status_code == 409
    docker.remove_container.assert_called_once_with("cid2")
    docker.start_container.assert_not_called()


def test_instance_deps_factories(monkeypatch, tmp_path):
    from app.services import instance_deps
    monkeypatch.setenv("ROUTE_BACKEND", "docker")
    monkeypatch.setattr(instance_deps, "DockerManager", lambda **k: MagicMock())
    monkeypatch.setattr(instance_deps, "_settings", MagicMock(
        SCREENSHOT_CACHE_DIR=str(tmp_path), DOCKER_NETWORK="n"))
    assert instance_deps.get_docker_manager() is not None
    assert instance_deps.get_screenshot_service() is not None
