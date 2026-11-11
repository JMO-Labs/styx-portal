"""Janitor purge of the abuse tables (schema per alembic 0002_abuse_tables)."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, bindparam, text

from app.config import settings
from app.services.janitor import fail_window, purge_expired

_DDL = (
    "CREATE TABLE auth_fail_events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind VARCHAR NOT NULL,"
    " key VARCHAR NOT NULL, username VARCHAR, at DATETIME NOT NULL)",
    "CREATE TABLE auth_blocks (kind VARCHAR NOT NULL, key VARCHAR NOT NULL, username VARCHAR,"
    " until DATETIME NOT NULL, PRIMARY KEY (kind, key))",
    "CREATE TABLE rate_counters (key VARCHAR NOT NULL, window_start DATETIME NOT NULL,"
    " count INTEGER NOT NULL, expires_at DATETIME NOT NULL, PRIMARY KEY (key, window_start))",
)
_TS = DateTime(timezone=True)
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


async def _exec(session, sql, **params):
    stmt = text(sql).bindparams(*(bindparam(k, type_=_TS) for k in params if k.startswith("t")))
    return await session.exec(stmt, params=params)


async def _seed(session):
    for ddl in _DDL:
        await session.exec(text(ddl))
    win = fail_window()
    for i, age in enumerate((win + 60, win + 120, win + 180, 30, win - 60)):
        await _exec(session, "INSERT INTO auth_fail_events (kind, key, at) VALUES ('ip', :k, :t)",
                    k=f"e{i}", t=NOW - timedelta(seconds=age))
    for i, delta in enumerate((-60, -120, -180, 300)):
        await _exec(session, "INSERT INTO auth_blocks (kind, key, until) VALUES ('user', :k, :t)",
                    k=f"b{i}", t=NOW + timedelta(seconds=delta))
        await _exec(session, "INSERT INTO rate_counters (key, window_start, count, expires_at) "
                    "VALUES (:k, :tw, 1, :t)", k=f"r{i}", tw=NOW - timedelta(seconds=600),
                    t=NOW + timedelta(seconds=delta))
    await session.commit()


async def _keys(session, table):
    return {r[0] for r in (await session.exec(text(f"SELECT key FROM {table}"))).all()}


def test_fail_window_covers_every_lockout_and_ban_window():
    assert fail_window() >= max(settings.LOCKOUT_DURATION, settings.BAN_FAIL_WINDOW)


async def test_janitor_purges_abuse_tables_in_batches(session):
    await _seed(session)
    n = await purge_expired(session, batch=2, now=NOW)
    assert n == 9
    assert await _keys(session, "auth_fail_events") == {"e3", "e4"}  # in-window survive
    assert await _keys(session, "auth_blocks") == {"b3"}
    assert await _keys(session, "rate_counters") == {"r3"}


async def test_janitor_keeps_recent_fail_events(session):
    await _seed(session)
    await purge_expired(session, now=NOW)
    assert "e4" in await _keys(session, "auth_fail_events")


async def test_janitor_skips_absent_abuse_tables(session):
    assert await purge_expired(session, now=NOW) == 0
