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
