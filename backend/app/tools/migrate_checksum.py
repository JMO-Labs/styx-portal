"""Per-table canonical-JSON SHA-256, identical on SQLite and PostgreSQL.

Rows are read through the app's own Table objects (so the same type processors
run on both engines) and hashed in Python, never in the database.
"""
import hashlib
import json
from datetime import date, datetime, time, timezone
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table on SQLModel.metadata)


def copy_tables() -> list[sa.Table]:
    """App tables in FK-dependency order; alembic_version is never copied or hashed."""
    return [t for t in SQLModel.metadata.sorted_tables if t.name != "alembic_version"]


def _canon(v):
    if isinstance(v, bool) or v is None or isinstance(v, (int, str)):
        return v
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, datetime):
        if v.tzinfo is not None:  # engines differ on tz-awareness; compare the UTC instant
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.isoformat()
    if isinstance(v, (date, time)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return bytes(v).hex()
    if isinstance(v, dict):
        return {str(k): _canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_canon(x) for x in v]
    return str(v)


def canonical_row(table: sa.Table, row) -> str:
    """One row as sorted-key compact JSON. Boolean columns are coerced (SQLite 0/1 -> bool)."""
    out = {}
    for name, value in dict(row).items():
        col = table.c.get(name)
        if value is not None and col is not None and isinstance(col.type, sa.Boolean):
            value = bool(value)
        out[name] = _canon(value)
    return json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


async def table_digest(conn, table: sa.Table) -> tuple[int, str]:
    order = list(table.primary_key.columns) or list(table.c)
    h, n = hashlib.sha256(), 0
    result = await conn.stream(sa.select(table).order_by(*order))
    async for row in result:
        h.update(canonical_row(table, row._mapping).encode())
        h.update(b"\n")
        n += 1
    return n, h.hexdigest()


async def checksum(engine: AsyncEngine, tables: list[sa.Table] | None = None) -> dict[str, tuple[int, str]]:
    """{table: (row_count, sha256)} read through one connection (read-only usage)."""
    async with engine.connect() as conn:
        return {t.name: await table_digest(conn, t) for t in (tables or copy_tables())}
