"""Single-transaction copy SQLite -> PostgreSQL with sequence reset and verify-or-rollback.

Everything on the target (optional TRUNCATE, inserts, sequence reset, checksum
verification) runs in ONE transaction that commits only if every table matches.
The source is only read. alembic_version is never copied or truncated.
"""
import hashlib
from typing import cast

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine

from app.tools.migrate_checksum import canonical_row, copy_tables, table_digest

CHUNK = 500


class PreflightError(Exception):
    """Preflight/usage failure (exit 2); never contains secrets."""


class VerifyMismatch(Exception):
    """Target differs from source after copy (exit 3, rolled back)."""


def sequence_tables(tables: list[sa.Table] | None = None) -> list[sa.Table]:
    """Tables with an integer autoincrement PK, derived from metadata."""
    return [t for t in (tables if tables is not None else copy_tables())
            if t.autoincrement_column is not None and isinstance(t.autoincrement_column.type, sa.Integer)]


async def read_source(src: AsyncEngine, tables: list[sa.Table], skipped: dict[str, set[tuple]]):
    """One connection, PK order; rows of preflight-skipped PKs are left out. Returns {table: [row dicts]}."""
    data = {}
    async with src.connect() as conn:
        for t in tables:
            pks = [c.name for c in t.primary_key.columns]
            if not pks:  # skip keys are PK tuples; PK-less tables are unsupported
                raise PreflightError(f"table {t.name} has no primary key")
            order = list(t.primary_key.columns) or list(t.c)
            skip = skipped.get(t.name, set())
            rows = [dict(r._mapping) for r in
                    (await conn.execute(sa.select(t).order_by(*order))).all()]
            data[t.name] = [r for r in rows if not (pks and tuple(r[c] for c in pks) in skip)]
    return data


def source_checksum(tables: list[sa.Table], data: dict[str, list[dict]]) -> dict[str, tuple[int, str]]:
    """Same digest as migrate_checksum.table_digest, over the (already filtered) source rows."""
    out = {}
    for t in tables:
        h = hashlib.sha256()
        for row in data[t.name]:
            h.update(canonical_row(t, row).encode())
            h.update(b"\n")
        out[t.name] = (len(data[t.name]), h.hexdigest())
    return out


async def target_checksum(conn, tables: list[sa.Table]) -> dict[str, tuple[int, str]]:
    """Digest of the target as seen inside the open transaction."""
    return {t.name: await table_digest(conn, t) for t in tables}


async def _non_empty(conn, tables) -> bool:
    for t in tables:
        if (await conn.execute(sa.select(sa.literal(1)).select_from(t).limit(1))).first():
            return True
    return False


async def _truncate(conn, tables) -> None:
    names = ", ".join(f'"{t.name}"' for t in tables)
    await conn.execute(sa.text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))  # nosec B608 - metadata names


async def _insert(conn, tables, data) -> None:
    for t in tables:  # sorted_tables: parents first
        rows = data[t.name]
        for i in range(0, len(rows), CHUNK):
            await conn.execute(t.insert(), rows[i:i + CHUNK])


async def _reset_sequences(conn, tables) -> None:
    for t in sequence_tables(tables):
        col = cast(sa.Column, t.autoincrement_column).name
        await conn.execute(sa.text(
            f'SELECT setval(pg_get_serial_sequence(:t, :c), COALESCE(MAX("{col}"), 1), MAX("{col}") IS NOT NULL) '  # nosec B608
            f'FROM "{t.name}"'), {"t": f'"{t.name}"', "c": col})


def _report(src: dict, dst: dict) -> bool:
    print("table rows_src rows_dst sha_src sha_dst")
    ok = True
    for name, a in src.items():
        b = dst[name]
        ok &= a == b
        print(f"{name} {a[0]} {b[0]} {a[1]} {b[1]}" + ("" if a == b else "  MISMATCH"))
    return ok


async def copy(src: AsyncEngine, dst: AsyncEngine, skipped: dict[str, set[tuple]] | None = None,
               replace: bool = False) -> None:
    """Copy + reset + verify in one target transaction. Raises PreflightError / VerifyMismatch."""
    tables = copy_tables()
    data = await read_source(src, tables, skipped or {})
    want = source_checksum(tables, data)
    async with dst.connect() as conn:
        tx = await conn.begin()
        try:
            if await _non_empty(conn, tables):
                if await target_checksum(conn, tables) == want:
                    print("already migrated")
                    return  # finally: rollback, nothing written
                if not replace:
                    raise PreflightError("target is not empty and differs from source; use --replace")
                await _truncate(conn, tables)
            await _insert(conn, tables, data)
            await _reset_sequences(conn, tables)
            got = await target_checksum(conn, tables)
            if not _report(want, got):
                raise VerifyMismatch()
            await tx.commit()
            print("migrated: all tables verified")
        finally:
            if tx.is_active:
                await tx.rollback()
