"""Idle-lock policy: per-group timeout, capped in the enterprise profile."""
from fastapi import HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import Group, User, UserGroup

DEFAULT_IDLE_LOCK_S = 900
MAX_IDLE_LOCK_MIN = 15


def validate_idle_lock(minutes: int | None) -> None:
    """422 when the enterprise profile gets 0 or more than 15 minutes."""
    if minutes is None or Settings().STYX_PROFILE != "enterprise":
        return
    if not 1 <= minutes <= MAX_IDLE_LOCK_MIN:
        raise HTTPException(422, f"idle_lock_minutes must be 1-{MAX_IDLE_LOCK_MIN} in enterprise")


async def effective_idle_lock_s(user: User, session: AsyncSession) -> int:
    """Smallest idle_lock_minutes across the user's groups, in seconds; 900 if none."""
    rows = (await session.exec(
        select(Group.idle_lock_minutes).join(UserGroup, col(UserGroup.group_id) == Group.id)
        .where(UserGroup.user_id == user.id))).all()
    vals = [m for m in rows if m]
    return min(vals) * 60 if vals else DEFAULT_IDLE_LOCK_S
