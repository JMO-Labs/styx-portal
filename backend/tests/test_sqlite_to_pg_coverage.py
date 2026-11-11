"""Cover _canon branches and the --verify-only path of _run (styx-portal#91)."""
import asyncio
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.tools import migrate_checksum as mc
from app.tools import sqlite_to_pg as tool
from tests.migrate_fixtures import make_source

PG = "postgresql+asyncpg://u:secretpw@localhost/db"


def test_canon_aware_datetime_normalised_to_utc():
    aware = datetime(2026, 1, 2, 5, 0, tzinfo=timezone(timedelta(hours=2)))
    assert mc._canon(aware) == "2026-01-02T03:00:00"


def test_canon_date_time_decimal_bytes():
    assert mc._canon(date(2026, 1, 2)) == "2026-01-02"
    assert mc._canon(time(3, 4, 5)) == "03:04:05"
    assert mc._canon(Decimal("1.50")) == "1.50"
    assert mc._canon(b"\x01\xff") == "01ff"
    assert mc._canon(memoryview(b"\x02")) == "02"


@pytest.mark.parametrize("flag,expected", [(0, 0), (3, 3)])
def test_verify_only_runs_verify_and_disposes(tmp_path, monkeypatch, flag, expected):
    src = asyncio.run(make_source(tmp_path / "s.db"))
    disposed = []

    class Eng:
        async def dispose(self):
            disposed.append(1)

    async def ok(_t):
        return None

    async def fake_verify(a, b):
        return expected

    monkeypatch.setattr(tool, "check_target_version", ok)
    monkeypatch.setattr(tool, "check_version", ok)
    monkeypatch.setattr(tool, "create_async_engine", lambda url, **kw: Eng())
    monkeypatch.setattr(tool, "verify", fake_verify)
    assert tool.main(["--source", str(src), "--target", PG, "--verify-only"]) == expected
    assert len(disposed) == 3  # preflight source, verify src, verify dst
