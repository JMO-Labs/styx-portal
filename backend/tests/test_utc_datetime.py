from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime
from sqlmodel import SQLModel, select

from app.db_types import UTCDateTime
from app.models import BannedIP

PLUS2 = timezone(timedelta(hours=2))


def _bind(value):
    return UTCDateTime().process_bind_param(value, None)


def test_bind_aware_converts_to_naive_utc():
    assert _bind(datetime(2026, 1, 1, 12, 0, tzinfo=PLUS2)) == datetime(2026, 1, 1, 10, 0)


def test_bind_naive_passthrough():
    naive = datetime(2026, 1, 1, 12, 0)
    assert _bind(naive) is naive


def test_bind_none():
    assert _bind(None) is None


def test_result_aware_becomes_naive_utc():
    got = UTCDateTime().process_result_value(datetime(2026, 1, 1, 12, tzinfo=PLUS2), None)
    assert got == datetime(2026, 1, 1, 10, 0) and got.tzinfo is None


async def test_roundtrip_returns_naive_utc(session):
    session.add(BannedIP(ip="10.0.0.1", expires_at=datetime(2026, 1, 1, 12, tzinfo=PLUS2)))
    await session.commit()
    got = (await session.exec(select(BannedIP.expires_at).where(BannedIP.ip == "10.0.0.1"))).one()
    assert got == datetime(2026, 1, 1, 10, 0)
    assert got.tzinfo is None


async def test_compare_aware_param(session):
    session.add(BannedIP(ip="10.0.0.2", expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc)))
    await session.commit()
    rows = (await session.exec(
        select(BannedIP).where(BannedIP.expires_at < datetime.now(timezone.utc)))).all()
    assert [r.ip for r in rows] == ["10.0.0.2"]


def test_all_model_datetime_columns_use_utcdatetime():
    bad = [f"{t.name}.{c.name}" for t in SQLModel.metadata.tables.values()
           for c in t.columns
           if isinstance(c.type, DateTime)]
    assert bad == []
    n = sum(isinstance(c.type, UTCDateTime)
            for t in SQLModel.metadata.tables.values() for c in t.columns)
    assert n >= 40
