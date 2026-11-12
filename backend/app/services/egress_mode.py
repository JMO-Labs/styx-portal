"""Per-user egress mode: strictest group wins."""
from sqlmodel import select

from app.models import Group, UserGroup


async def resolve_egress_mode(session, user) -> str:
    r = await session.exec(
        select(Group.id).join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user.id, Group.egress_mode == "allowlist"))
    return "allowlist" if r.first() is not None else "category"
