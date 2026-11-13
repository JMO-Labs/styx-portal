"""Portal notices (ADR-0059): idempotent per (user, kind, key)."""
from datetime import datetime

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Notice


async def post_notice(session: AsyncSession, user_id: str, kind: str, key: str,
                      message: str, due_at: datetime | None = None,
                      created_at: datetime | None = None) -> Notice:
    """Create the notice, or return the existing row for (user_id, kind, key)."""
    existing = (await session.exec(select(Notice).where(
        Notice.user_id == user_id, Notice.kind == kind, Notice.key == key))).first()
    if existing:
        return existing
    notice = Notice(user_id=user_id, kind=kind, key=key, message=message, due_at=due_at)
    if created_at is not None:
        notice.created_at = created_at
    session.add(notice)
    await session.commit()
    await session.refresh(notice)
    return notice
