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
    from app.models import Instance, ServiceTemplate
    if not await session.get(ServiceTemplate, "t"):
        session.add(ServiceTemplate(id="t", name="tpl-t", display_name="T", image="img"))
        await session.commit()
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


_ALL_LOOPS = ("_session_monitor_loop", "_service_health_loop", "_metrics_db_loop",
              "_metrics_sampler_loop", "_screenshot_capture_loop", "_health_sample_loop",
              "service_thumbnail_loop", "prepull_loop")
_LEADER_LOOPS = ("_session_monitor_loop", "_service_health_loop", "_metrics_db_loop")
_REPLICA_LOOPS = ("_metrics_sampler_loop", "_screenshot_capture_loop", "_health_sample_loop",
                  "service_thumbnail_loop")
_BOOT = ("reconcile", "close_dangling", "probe_cleanup")


async def _run_lifespan(monkeypatch, elector=None, k8s=False):
    """Run the real lifespan with loops/boot steps recorded. ``elector=None``
    leaves the real get_elector() in place (SQLite stub, always leader)."""
    import asyncio
    import app.main as m
    import app.services.leader as leader_mod
    import app.services.route_writer as rw
    import app.services.stream_sessions as stream_sessions

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel

    # Hermetic DB: never touch the configured on-disk DATABASE_URL.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)

    async def init_db():
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    monkeypatch.setattr(m, "init_db", init_db)
    monkeypatch.setattr(m, "async_session",
                        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False))

    events = []

    def fake(name):
        async def _loop(*a, **k):
            events.append(name)
            await asyncio.Event().wait()
        return _loop

    def record(name):
        async def _step(*a, **k):
            events.append(name)
        return _step

    class _DM:
        def __init__(self, *a, **k):
            pass

        def remove_probe_containers(self):
            events.append("probe_cleanup")
            return 0

    for attr in _ALL_LOOPS:
        monkeypatch.setattr(m, attr, fake(attr))
    monkeypatch.setattr(m, "_reconcile_instances_at_boot", record("reconcile"))
    monkeypatch.setattr(m, "_log_portal_instances", record("log_instances"))
    monkeypatch.setattr(stream_sessions, "close_dangling", record("close_dangling"))
    monkeypatch.setattr(rw, "refresh_routes_from_db", record("refresh_routes"))
    monkeypatch.setattr(m, "DockerManager", _DM)
    monkeypatch.setattr(m, "instance_runtime", lambda: object())
    if elector is None:
        monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
        monkeypatch.setenv("LEADER_DATABASE_URL", "")
        monkeypatch.setattr(leader_mod, "_elector", None)
    else:
        monkeypatch.setattr(m, "get_elector", lambda: elector)
    monkeypatch.setattr(m, "start_metrics_server", lambda *a: None)
    monkeypatch.setattr(m._settings, "ROUTE_BACKEND", "k8s" if k8s else "file")
    monkeypatch.setattr(m._settings, "JWT_SECRET", "x" * 40, raising=False)
    async with m.lifespan(m.app):
        await asyncio.sleep(0.05)
    await engine.dispose()
    return events


@pytest.mark.asyncio
@pytest.mark.parametrize("leader", [False, True])
async def test_lifespan_gates_leader_only_loops(monkeypatch, leader):
    events = await _run_lifespan(monkeypatch, _FakeElector(leader))
    for name in _LEADER_LOOPS:
        assert (name in events) is leader
    for name in _BOOT:
        assert events.count(name) == (1 if leader else 0), name
    for name in _REPLICA_LOOPS:
        assert name in events


@pytest.mark.asyncio
async def test_lifespan_non_leader_k8s_skips_prepull(monkeypatch):
    events = await _run_lifespan(monkeypatch, _FakeElector(False), k8s=True)
    assert "prepull_loop" not in events
    assert "_metrics_sampler_loop" in events


@pytest.mark.asyncio
async def test_lifespan_sqlite_starts_all_loops_as_before(monkeypatch):
    events = await _run_lifespan(monkeypatch)  # real get_elector() on SQLite
    for name in _LEADER_LOOPS + _REPLICA_LOOPS:
        assert name in events, name
    for name in _BOOT:
        assert events.count(name) == 1, name
    assert "prepull_loop" not in events


@pytest.mark.asyncio
async def test_lifespan_refreshes_routes_after_reconcile(monkeypatch):
    events = await _run_lifespan(monkeypatch, _FakeElector(True))
    refreshes = [i for i, e in enumerate(events) if e == "refresh_routes"]
    assert refreshes[0] < events.index("reconcile")  # per-replica initial routes
    assert refreshes[-1] > events.index("reconcile")  # leader re-writes after reconcile
    assert refreshes[-1] > events.index("close_dangling")
