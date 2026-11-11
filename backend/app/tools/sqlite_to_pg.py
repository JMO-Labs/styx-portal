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
from sqlmodel import SQLModel

from app.db_migrate import alembic_config
from app.tools import migrate_preflight
from app.tools.migrate_checksum import checksum

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


async def check_target_empty(target: str) -> None:
    """Require every known table in the target to be empty. Never echoes driver errors."""
    shown = _safe(target)
    engine = create_async_engine(target)
    try:
        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: set(sqlalchemy.inspect(c).get_table_names()))
            for name in sorted(SQLModel.metadata.tables):
                if name in names and (await conn.execute(
                        sqlalchemy.text(f'SELECT 1 FROM "{name}" LIMIT 1'))).first():
                    raise PreflightError(f"target {shown} is not empty (table {name}); use --replace")
    except PreflightError:
        raise
    except Exception:
        raise PreflightError(f"cannot inspect target {shown}") from None
    finally:
        await engine.dispose()


def run_preflight(source: Path, drop_orphans: bool) -> migrate_preflight.ScanResult:
    """Scan the source; print findings; raise on anything that blocks."""
    res = migrate_preflight.scan(source, drop_orphans=drop_orphans)
    blocking = res.blocking if drop_orphans else res.findings
    for pk_table, pks in sorted(res.skipped.items()):
        for pk in sorted(pks, key=str):
            print(f"skipped {pk_table} {','.join(map(str, pk))}")
    if blocking:
        for f in blocking:
            print(f"finding: {f}", file=sys.stderr)
        hint = "" if drop_orphans or not any(f.kind == "orphan" for f in blocking) else \
            " (orphan FK rows can be skipped with --drop-orphans)"
        raise PreflightError(f"{len(blocking)} source finding(s); target untouched{hint}")
    return res


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


async def verify(src: AsyncEngine, dst: AsyncEngine) -> int:
    """Compare per-table row counts and checksums; no writes. 0 match, 3 mismatch."""
    a, b = await checksum(src), await checksum(dst)
    print("table rows_src rows_dst sha_src sha_dst")
    bad = False
    for name, (n_src, sha_src) in a.items():
        n_dst, sha_dst = b[name]
        bad |= (n_src, sha_src) != (n_dst, sha_dst)
        print(f"{name} {n_src} {n_dst} {sha_src} {sha_dst}" + ("" if (n_src, sha_src) == (n_dst, sha_dst) else "  MISMATCH"))
    return EXIT_VERIFY if bad else EXIT_OK


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
    res = run_preflight(source, args.drop_orphans)
    await check_target_version(target)
    if args.verify_only:
        src, dst = open_source(source), create_async_engine(target)
        try:
            return await verify(src, dst)
        finally:
            await src.dispose()
            await dst.dispose()
    if args.dry_run:
        if not args.replace:
            await check_target_empty(target)
        for table, n in res.counts.items():
            print(f"{table}: {n}")
        print("dry-run: no changes made")
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
