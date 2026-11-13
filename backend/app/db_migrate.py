"""Database schema startup: Alembic upgrade plus the one-time legacy SQLite stamp."""
import logging
import os
import sqlite3
from pathlib import Path

import sqlalchemy
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import SQLModel

import app.models  # noqa: F401  (registers every table on SQLModel.metadata)

logger = logging.getLogger("styx-portal")

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
BASELINE = "0001_baseline"
BACKUP_SUFFIX = ".pre-alembic.bak"
PG_MIGRATE_LOCK = 0x5717_0001  # pg_advisory_xact_lock key: one replica migrates at a time


def alembic_config(connection=None) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def _stamp_baseline(sync_conn) -> None:
    command.stamp(alembic_config(sync_conn), BASELINE)


def _upgrade_head(sync_conn) -> None:
    command.upgrade(alembic_config(sync_conn), "head")


def _backup_sqlite(path: str) -> None:
    """Copy the DB to <db>.pre-alembic.bak (0600). An existing backup is the oldest
    pre-Alembic copy and is never overwritten."""
    bak = Path(f"{path}{BACKUP_SUFFIX}")
    if bak.exists():
        return
    os.close(os.open(bak, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600))
    src, dst = sqlite3.connect(path), sqlite3.connect(bak)
    try:
        src.backup(dst)
    finally:
        src.close()
        dst.close()
    logger.info("Backed up pre-Alembic database to %s", bak)


async def migrate(engine: AsyncEngine) -> None:
    """Bring the schema to Alembic head. See docs/operate/upgrade.md."""
    url = engine.url
    backend = url.get_backend_name()
    logger.info("Database: %s", url.render_as_string(hide_password=True))
    async with engine.begin() as conn:
        if backend == "postgresql":
            await conn.execute(sqlalchemy.text("SELECT pg_advisory_xact_lock(:k)"),
                               {"k": PG_MIGRATE_LOCK})
        tables = await conn.run_sync(lambda c: set(inspect(c).get_table_names()))
        if tables and "alembic_version" not in tables:
            if backend != "sqlite":
                raise RuntimeError(
                    f"{backend} database has tables but no alembic_version table; "
                    "refusing to start. Point DATABASE_URL at an empty database or one "
                    "created by Styx.")
            logger.warning("Legacy SQLite database: backing up and stamping %s", BASELINE)
            if url.database not in (None, "", ":memory:"):
                _backup_sqlite(url.database)  # before any DDL
            await _run_migrations(conn)
            await conn.run_sync(SQLModel.metadata.create_all)
            await conn.run_sync(_stamp_baseline)
        await conn.run_sync(_upgrade_head)


_TEMPLATE_COLUMN_DDL = {
    "shared": "BOOLEAN DEFAULT 0",
    "restart_policy": "TEXT DEFAULT 'no'",
    "read_only_rootfs": "BOOLEAN DEFAULT 0",
    "tmpfs": "JSON DEFAULT '[]'",
    "extra_hosts": "JSON DEFAULT '{}'",
    "ulimits": "JSON DEFAULT '[]'",
    "extra_ports": "JSON DEFAULT '[]'",
    "entrypoint": "JSON",
    "command": "JSON",
    "devices": "JSON DEFAULT '[]'",
    "privileged": "BOOLEAN DEFAULT 0",
    "extra_docker_args": "JSON DEFAULT '{}'",
}


def _ensure_template_columns(conn) -> None:
    """Add missing columns to service_templates table. Works with both sqlite3 and SQLAlchemy connections."""
    # Handle both raw sqlite3 and SQLAlchemy connections
    # Check if this is an async SQLAlchemy connection (has run_sync method)
    if hasattr(conn, 'run_sync'):
        # This is an async SQLAlchemy connection - this case is handled in async wrapper
        raise TypeError("Use _ensure_template_columns_async for SQLAlchemy async connections")

    # Raw sqlite3 connection
    existing = {r[1] for r in conn.execute("PRAGMA table_info(service_templates)")}
    for col, ddl in _TEMPLATE_COLUMN_DDL.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE service_templates ADD COLUMN {col} {ddl}")
    conn.commit()


async def _run_migrations(conn):
    """FROZEN legacy SQLite step: adds columns that pre-Alembic releases lacked.

    Runs only once, on a SQLite DB without ``alembic_version``, right before the
    baseline stamp. Never extend it: every new schema change is an Alembic revision.
    """

    migrations = [
        ("instances", "error_message", "TEXT"),
        ("instances", "status_detail", "TEXT"),
        ("instances", "owner_id", "TEXT"),
        ("service_templates", "owner_id", "TEXT"),
        ("service_templates", "dind", "BOOLEAN"),
        ("service_templates", "cap_add", "TEXT"),
        ("service_templates", "security_opt", "TEXT"),
        ("service_templates", "tls_skip_verify", "BOOLEAN"),
        ("service_templates", "shared", "BOOLEAN DEFAULT 0"),
        ("service_templates", "restart_policy", "TEXT DEFAULT 'no'"),
        ("service_templates", "read_only_rootfs", "BOOLEAN DEFAULT 0"),
        ("service_templates", "tmpfs", "JSON DEFAULT '[]'"),
        ("service_templates", "extra_hosts", "JSON DEFAULT '{}'"),
        ("service_templates", "ulimits", "JSON DEFAULT '[]'"),
        ("service_templates", "extra_ports", "JSON DEFAULT '[]'"),
        ("service_templates", "entrypoint", "JSON"),
        ("service_templates", "command", "JSON"),
        ("service_templates", "devices", "JSON DEFAULT '[]'"),
        ("service_templates", "privileged", "BOOLEAN DEFAULT 0"),
        ("service_templates", "extra_docker_args", "JSON DEFAULT '{}'"),
        ("oauth_providers", "icon_url", "TEXT"),
        ("oauth_providers", "trust_email", "BOOLEAN"),
        ("oauth_providers", "allow_signup", "BOOLEAN"),
        ("oauth_providers", "auto_promote_admins", "BOOLEAN"),
        ("refresh_tokens", "family_id", "TEXT"),
        ("workstations", "active_connections", "INTEGER"),
        ("workstations", "occupied_by", "TEXT"),
        ("workstations", "occupied_at", "TIMESTAMP"),
        ("workstations", "disconnect_pending", "BOOLEAN"),
        ("workstations", "idle_disconnect_sent", "BOOLEAN NOT NULL DEFAULT 0"),
        ("workstations", "icon", "TEXT"),
        ("workstations", "update_target", "TEXT NOT NULL DEFAULT ''"),
        ("workstations", "update_state", "TEXT NOT NULL DEFAULT ''"),
        ("workstations", "update_error", "TEXT"),
        ("workstations", "update_at", "TIMESTAMP"),
        ("users", "failed_count", "INTEGER DEFAULT 0"),
        ("users", "token_version", "INTEGER NOT NULL DEFAULT 0"),
        ("service_presets", "subpath", "JSON"),
        ("proxied_services", "mount_managed", "BOOLEAN NOT NULL DEFAULT 0"),
        ("mount_jobs", "changed", "BOOLEAN NOT NULL DEFAULT 0"),
        ("proxied_services", "pass_identity", "BOOLEAN NOT NULL DEFAULT 0"),
        ("proxied_services", "frame_ok", "BOOLEAN NOT NULL DEFAULT 1"),
        ("users", "locked_until", "TIMESTAMP"),
        ("proxied_services", "icon_custom", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "open_workspaces", "TEXT"),
        ("users", "open_apps", "TEXT"),
        ("proxied_services", "upstream_is_proxy", "BOOLEAN NOT NULL DEFAULT 0"),
        ("users", "matrix_card", "TEXT"),
        ("users", "matrix_pending", "TEXT"),
        ("users", "matrix_challenge", "TEXT"),
        ("users", "matrix_serial", "INTEGER NOT NULL DEFAULT 0"),
        ("refresh_tokens", "session_only", "INTEGER NOT NULL DEFAULT 0"),
        ("service_templates", "profile_mount", "TEXT"),
        ("instances", "profile_volume", "TEXT"),
        ("instances", "gpu", "BOOLEAN"),
        ("instances", "notice", "TEXT"),
        ("user_profiles", "last_used_at", "TIMESTAMP"),
        ("groups", "allow_gpu", "BOOLEAN DEFAULT 0"),
        ("groups", "egress_mode", "TEXT NOT NULL DEFAULT 'category'"),
        ("groups", "dlp_clipboard_in", "BOOLEAN"),
        ("groups", "dlp_clipboard_out", "BOOLEAN"),
        ("groups", "dlp_upload", "BOOLEAN"),
        ("groups", "dlp_download", "BOOLEAN"),
        ("groups", "dlp_printing", "BOOLEAN"),
        ("groups", "dlp_watermark", "BOOLEAN"),
        ("groups", "dlp_approval_ref", "TEXT"),
        ("groups", "dlp_approved_at", "DATETIME"),
    ]
    for table, column, col_type in migrations:
        try:
            await conn.execute(sqlalchemy.text(
                f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
            ))
        except OperationalError as e:
            msg = str(e).lower()
            # expected on fresh installs / re-runs; anything else is a real failure
            if "duplicate column" not in msg and "no such table" not in msg:
                logger.error("Migration failed for %s.%s: %s", table, column, e)
                raise

    # ADD COLUMN ... BOOLEAN has no default, so rows that predate a column get NULL.
    # These are non-nullable bools downstream — backfill NULLs to False.
    backfills = [
        ("oauth_providers", "trust_email", "0"),
        ("oauth_providers", "allow_signup", "0"),
        ("oauth_providers", "auto_promote_admins", "1"),
        ("service_templates", "tls_skip_verify", "0"),
        ("refresh_tokens", "family_id", "jti"),  # legacy rows: own family
        ("workstations", "active_connections", "0"),
        ("workstations", "disconnect_pending", "0"),
        ("users", "failed_count", "0"),
    ]
    for table, column, default in backfills:
        try:
            await conn.execute(sqlalchemy.text(
                f"UPDATE {table} SET {column} = {default} WHERE {column} IS NULL"
            ))
        except OperationalError as e:
            if "no such table" not in str(e).lower():
                logger.error("Backfill failed for %s.%s: %s", table, column, e)
                raise

    # Service icons are stored like workstation icons: None, "emoji:<char>" or a data: URI.
    # Older rows hold a bare preset emoji.
    for stmt in (
        "UPDATE proxied_services SET icon = NULL WHERE icon = ''",
        "UPDATE proxied_services SET icon = 'emoji:' || icon WHERE icon IS NOT NULL "
        "AND icon NOT LIKE 'emoji:%' AND icon NOT LIKE 'data:%'",
    ):
        try:
            await conn.execute(sqlalchemy.text(stmt))
        except OperationalError as e:
            if "no such table" not in str(e).lower():
                logger.error("Service icon migration failed: %s", e)
                raise
