"""SQLite -> PostgreSQL migration tool (CLI skeleton).

Usage: python -m app.tools.sqlite_to_pg --source <db> [--target URL]
       [--dry-run | --verify-only] [--replace] [--drop-orphans]

Exit codes: 0 ok, 2 preflight/usage failure, 3 verify mismatch.
The source is opened strictly read-only and is never upgraded.
"""
import argparse
import asyncio
import os
import sys
from pathlib import Path

import sqlalchemy
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.db_migrate import alembic_config

EXIT_OK, EXIT_PREFLIGHT, EXIT_VERIFY = 0, 2, 3


class PreflightError(Exception):
    """A preflight/usage failure (exit 2). Messages must never contain secrets."""


def source_url(path: Path) -> str:
    # uri=true is required, else SQLAlchemy ignores mode=ro and opens a file named "file:<path>".
    return f"sqlite+aiosqlite:///file:{Path(path).resolve()}?mode=ro&uri=true"


def open_source(path: Path) -> AsyncEngine:
    return create_async_engine(source_url(path))


def code_head() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


async def check_version(engine: AsyncEngine) -> str:
    """Require source alembic_version == code head (the target is checked by check_target_version)."""
    head = code_head()
    hint = (f"start the new release once on SQLite so it migrates the source to {head}, "
            "then re-run (this tool never upgrades the source)")
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(sqlalchemy.text("SELECT version_num FROM alembic_version"))).all()
    except OperationalError:
        raise PreflightError(f"source is not stamped with an Alembic version: {hint}") from None
    if len(rows) != 1:
        raise PreflightError(f"source is not stamped with an Alembic version: {hint}")
    if rows[0][0] != head:
        raise PreflightError(f"source version {rows[0][0]} != code head {head}: {hint}")
    return head


async def check_target_version(target: str) -> None:
    """Require the target's alembic_version == code head. Never echoes driver errors (DSN leak)."""
    head = code_head()
    hint = f"start the new release once on PostgreSQL so it migrates the target to {head}, then re-run"
    shown = _safe(target)
    try:
        engine = create_async_engine(target)
    except Exception:
        raise PreflightError(f"cannot open target {shown}") from None
    try:
        async with engine.connect() as conn:
            rows = (await conn.execute(sqlalchemy.text("SELECT version_num FROM alembic_version"))).all()
    except Exception:
        raise PreflightError(
            f"target {shown} is unreachable or not stamped with an Alembic version: {hint}") from None
    finally:
        await engine.dispose()
    if len(rows) != 1 or rows[0][0] != head:
        found = rows[0][0] if len(rows) == 1 else "<none>"
        raise PreflightError(f"target {shown} version {found} != code head {head}: {hint}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="python -m app.tools.sqlite_to_pg",
                                description="Copy a Styx SQLite database to PostgreSQL.")
    p.add_argument("--source", required=True, help="path to the SQLite database")
    p.add_argument("--target", default=None, help="PostgreSQL URL (default: $DATABASE_URL)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--verify-only", action="store_true")
    p.add_argument("--replace", action="store_true")
    p.add_argument("--drop-orphans", action="store_true")
    return p.parse_args(argv)


def _validate_target(raw: str | None) -> str:
    raw = raw or os.environ.get("DATABASE_URL", "")
    if not raw.startswith("postgresql"):
        shown = "<unset>" if not raw else _safe(raw)
        raise PreflightError(f"target must be a postgresql URL, got {shown}")
    return raw


def _safe(raw: str) -> str:
    try:
        return make_url(raw).render_as_string(hide_password=True)
    except Exception:
        return "<unparseable url>"


async def _run(args: argparse.Namespace) -> int:
    source = Path(args.source).resolve()
    if not source.is_file():
        raise PreflightError(f"source file not found: {source}")
    target = _validate_target(args.target)
    print(f"source: {source}\ntarget: {_safe(target)}")
    engine = open_source(source)
    try:
        await check_version(engine)
    finally:
        await engine.dispose()
    await check_target_version(target)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_run(args))
    except PreflightError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_PREFLIGHT


if __name__ == "__main__":
    sys.exit(main())
