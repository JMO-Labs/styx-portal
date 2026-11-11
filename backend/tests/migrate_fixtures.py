"""Helpers to build SQLite source DBs for sqlite_to_pg tests."""
import sqlite3
from pathlib import Path

from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import create_async_engine

from app.db_migrate import migrate


async def make_source(path: Path) -> Path:
    """Fresh SQLite file migrated to Alembic head by the app's own migrate()."""
    eng = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    try:
        await migrate(eng)
    finally:
        await eng.dispose()
    return path


def raw_exec(path: Path, sql: str, params: tuple = ()) -> None:
    """Run raw SQL (lets tests plant bad data)."""
    con = sqlite3.connect(path)
    try:
        con.execute(sql, params)
        con.commit()
    finally:
        con.close()
