"""One-time first-run setup code, stored in the DB so every replica agrees.

While no user exists, POST /api/auth/setup must present this code. It is a
singleton row (id=1) created with INSERT ... ON CONFLICT DO NOTHING, so racing
issuers converge on one token, and consumed with a DELETE whose rowcount decides
the single winner. A pre-DB `<data dir>/setup-token` file is migrated at boot.
"""
import asyncio
import logging
import secrets
from pathlib import Path
from typing import cast

from sqlalchemy import delete
from sqlalchemy.dialects import postgresql, sqlite
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import SetupToken

logger = logging.getLogger("styx-portal")
_settings = Settings()

# Serialises first-run creation within a process; the DB guard covers replicas.
setup_lock = asyncio.Lock()


def _legacy_path() -> Path:
    return Path(_settings.SECRETS_FILE).parent / "setup-token"


def take_legacy_file() -> str | None:
    """Read and delete the old per-pod token file, if present."""
    p = _legacy_path()
    try:
        tok = p.read_text().strip()
    except FileNotFoundError:
        return None
    p.unlink(missing_ok=True)
    return tok or None


async def current_or_none(session: AsyncSession) -> str | None:
    return (await session.exec(select(SetupToken.token).where(SetupToken.id == 1))).first()


async def _insert_if_absent(session: AsyncSession, token: str) -> None:
    bind = session.bind
    ins = (postgresql.insert if bind is not None and bind.dialect.name == "postgresql" else sqlite.insert)
    await session.exec(ins(SetupToken).values(id=1, token=token).on_conflict_do_nothing())
    await session.commit()


async def current(session: AsyncSession) -> str:
    """The active setup code, atomically creating it if missing."""
    tok = await current_or_none(session)
    if tok is None:
        await _insert_if_absent(session, secrets.token_urlsafe(24))
        tok = await current_or_none(session)
    return cast(str, tok)


async def verify(session: AsyncSession, candidate: str | None) -> bool:
    """Read-only check; never mints a token (announce() does that at boot)."""
    if not candidate:
        return False
    tok = await current_or_none(session)
    return tok is not None and secrets.compare_digest(candidate.encode(), tok.encode())


async def consume(session: AsyncSession, candidate: str | None) -> bool:
    """Delete the token iff it matches; True for exactly one caller. Caller commits."""
    if not await verify(session, candidate):
        return False
    res = await session.exec(delete(SetupToken).where(
        col(SetupToken.id) == 1, col(SetupToken.token) == candidate))
    return res.rowcount == 1


async def clear(session: AsyncSession) -> None:
    await session.exec(delete(SetupToken))
    await session.commit()


async def announce(session: AsyncSession, setup_pending: bool) -> None:
    """Boot hook: log the code while setup is pending, else drop stale state."""
    legacy = take_legacy_file()
    if not setup_pending:
        await clear(session)
        return
    if legacy:
        await _insert_if_absent(session, legacy)
    logger.warning("Styx setup code: %s  (needed to create the first admin)",
                   await current(session))
