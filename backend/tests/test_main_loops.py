from unittest.mock import AsyncMock

import docker.errors
import pytest

import app.services.background_loops as main
import app.services.route_writer as route_writer
import app.services.workstations as workstations


@pytest.mark.asyncio
async def test_monitor_pass_docker_error_still_marks_workstations(monkeypatch):
    """With no Docker (k8s), the Docker pass raises every tick; workstation
    offline-marking and route refresh must still run."""
    async def failing_pass(session, monitor, dock):
        raise docker.errors.DockerException("no docker")

    mark = AsyncMock(return_value=True)
    refresh = AsyncMock()
    session = AsyncMock()

    monkeypatch.setattr(main, "_run_monitor_pass", failing_pass)
    monkeypatch.setattr(workstations, "mark_stale_offline", mark)
    monkeypatch.setattr(route_writer, "refresh_routes_from_db", refresh)

    await main._monitor_tick(session, object(), object())

    mark.assert_awaited_once_with(session)
    refresh.assert_awaited_once_with(session)
    session.commit.assert_awaited_once()


class _Docker:
    def __init__(self, fn):
        self.get_container_status = fn


async def _seed(session, statuses):
    from app.models import Instance
    insts = [Instance(name=f"i{n}", subdomain=f"s{n}", template_id="t", status=st, container_id=f"c{n}")
             for n, st in enumerate(statuses)]
    for i in insts:
        session.add(i)
    await session.commit()
    return insts


@pytest.mark.asyncio
async def test_boot_reconcile_survives_docker_down(session):
    insts = await _seed(session, ["running", "idle"])

    def boom(_cid):
        raise docker.errors.DockerException("no docker")

    await main._reconcile_instances_at_boot(session, _Docker(boom))
    for i in insts:
        await session.refresh(i)
        assert i.status == "stopped"


@pytest.mark.asyncio
async def test_boot_reconcile_docker_up_unchanged(session):
    up, gone = await _seed(session, ["running", "running"])
    st = {up.container_id: "running", gone.container_id: "not_found"}
    await main._reconcile_instances_at_boot(session, _Docker(lambda c: {"status": st[c]}))
    await session.refresh(up)
    await session.refresh(gone)
    assert (up.status, gone.status) == ("running", "stopped")


class _FakeElector:
    def __init__(self, leader):
        self.is_leader = leader

    async def run(self, on_elected=None, on_lost=None):
        import asyncio
        if self.is_leader and on_elected:
            await on_elected()
        await asyncio.Event().wait()

    async def stop(self):
        pass


async def _run_lifespan(monkeypatch, leader):
    import asyncio
    import app.main as m

    started = []

    def fake(name):
        async def _loop(*a, **k):
            started.append(name)
            await asyncio.Event().wait()
        return _loop

    async def noop(*a, **k):
        return None

    for attr in ("_session_monitor_loop", "_service_health_loop", "_metrics_db_loop",
                 "_metrics_sampler_loop", "_screenshot_capture_loop", "_health_sample_loop",
                 "service_thumbnail_loop", "prepull_loop"):
        monkeypatch.setattr(m, attr, fake(attr))
    monkeypatch.setattr(m, "_reconcile_instances_at_boot", noop)
    monkeypatch.setattr(m, "get_elector", lambda: _FakeElector(leader))
    monkeypatch.setattr(m, "start_metrics_server", lambda *a: None)
    monkeypatch.setattr(m._settings, "ROUTE_BACKEND", "k8s")
    monkeypatch.setattr(m._settings, "JWT_SECRET", "x" * 40, raising=False)
    async with m.lifespan(m.app):
        await asyncio.sleep(0.05)
    return started


@pytest.mark.asyncio
async def test_lifespan_gates_leader_only_loops(monkeypatch):
    started = await _run_lifespan(monkeypatch, leader=False)
    for name in ("_session_monitor_loop", "_service_health_loop", "_metrics_db_loop", "prepull_loop"):
        assert name not in started
    for name in ("_metrics_sampler_loop", "_health_sample_loop", "service_thumbnail_loop"):
        assert name in started


@pytest.mark.asyncio
async def test_lifespan_sqlite_starts_all_loops_as_before(monkeypatch):
    started = await _run_lifespan(monkeypatch, leader=True)
    for name in ("_session_monitor_loop", "_service_health_loop", "_metrics_db_loop",
                 "prepull_loop", "_metrics_sampler_loop", "_health_sample_loop",
                 "service_thumbnail_loop"):
        assert name in started
