import asyncio
from unittest.mock import patch

from app.config import Settings
from app.services.leader import LeaderElector


def _sqlite_elector():
    return LeaderElector(Settings(DATABASE_URL="sqlite+aiosqlite:///:memory:"))


def test_leader_url_defaults_to_database_url():
    s = Settings(DATABASE_URL="postgresql+asyncpg://a/b", LEADER_DATABASE_URL="")
    assert s.leader_url() == "postgresql+asyncpg://a/b"
    s = Settings(DATABASE_URL="postgresql+asyncpg://a/b", LEADER_DATABASE_URL="postgresql://c/d")
    assert s.leader_url() == "postgresql://c/d"


def test_timing_defaults():
    s = Settings()
    assert (s.LEADER_RETRY_S, s.LEADER_HEARTBEAT_S) == (5.0, 5.0)
    assert (s.LEADER_HEARTBEAT_TIMEOUT_S, s.LEADER_FENCE_S) == (3.0, 15.0)


async def test_sqlite_is_always_leader_without_connection():
    el = _sqlite_elector()
    assert el.is_leader is True
    elected = asyncio.Event()

    async def on_elected():
        elected.set()

    with patch("asyncpg.connect") as connect:
        task = asyncio.create_task(el.run(on_elected, lambda: None))
        await asyncio.wait_for(elected.wait(), 1)
        await el.stop()
        await asyncio.wait_for(task, 1)
    connect.assert_not_called()
    assert el.is_leader is True


async def test_diagnostics_reports_leader(session, tmp_path, monkeypatch):
    from app.services import diagnostics
    monkeypatch.setattr(diagnostics._settings, "TRAEFIK_DYNAMIC_DIR", str(tmp_path))

    class _D:
        def ping(self): return True
        def version(self): return "x"

    r = await diagnostics.run_diagnostics(session, docker=_D())
    assert r["leader"] is True
    assert "leader" not in {c["key"] for c in r["checks"]}


# --- LeaderTasks ---
from app.services.leader import LeaderTasks  # noqa: E402


async def test_leader_tasks_cancelled_on_loss():
    started, cancelled = asyncio.Event(), asyncio.Event()

    async def loop():
        started.set()
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    lt = LeaderTasks(boot=[], loops=[loop])
    await lt.on_elected()
    await asyncio.wait_for(started.wait(), 1)
    await lt.on_lost()
    assert cancelled.is_set()
    assert lt.running is False


async def test_promotion_runs_boot_steps_each_time():
    calls = []

    async def boot():
        calls.append("boot")

    async def loop():
        await asyncio.sleep(3600)

    lt = LeaderTasks(boot=[boot], loops=[loop])
    await lt.on_elected()
    await lt.on_lost()
    await lt.on_elected()
    await lt.stop()
    assert calls == ["boot", "boot"]


async def test_task_crash_does_not_kill_elector(caplog):
    ran = asyncio.Event()

    async def bad_boot():
        raise RuntimeError("boom")

    async def bad_loop():
        ran.set()
        raise RuntimeError("loop boom")

    lt = LeaderTasks(boot=[bad_boot], loops=[bad_loop])
    el = _sqlite_elector()
    task = asyncio.create_task(el.run(lt.on_elected, lt.on_lost))
    await asyncio.wait_for(ran.wait(), 1)
    await asyncio.sleep(0.05)
    assert not task.done()
    await el.stop()
    await lt.stop()
    await asyncio.wait_for(task, 1)
    assert "boom" in caplog.text
