"""Immutable, never-reused POSIX UID allocator (ADR-0052 / D52).

Append-only: rows are inserted, never updated or deleted.
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import PosixUid


async def _existing(session: AsyncSession, user_key: str) -> int | None:
    return (await session.exec(
        select(PosixUid.uid).where(PosixUid.user_key == user_key))).first()


async def allocate_uid(session: AsyncSession, user_key: str) -> int:
    """Return user_key's UID, allocating max(ever allocated)+1 (>= POSIX_UID_MIN) if new."""
    for _ in range(5):
        if (uid := await _existing(session, user_key)) is not None:
            return uid
        top = (await session.exec(select(func.max(PosixUid.uid)))).one()
        uid = max(Settings().POSIX_UID_MIN, (top + 1) if top is not None else 0)
        try:
            async with session.begin_nested():
                session.add(PosixUid(uid=uid, user_key=user_key))
            await session.commit()
            return uid
        except IntegrityError:  # concurrent allocation took this uid/user_key: retry
            continue
    raise RuntimeError("could not allocate POSIX UID")
