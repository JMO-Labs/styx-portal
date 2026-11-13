"""One helper: SessionEvent row + ECS ``styx.audit`` session line (#235)."""
import os
import socket

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Group, Instance, SessionEvent, User, UserGroup
from app.services.audit_ecs import emit, session_event


async def record_session_event(session: AsyncSession, instance: Instance, event_type: str, *,
                               action: str | None = None, reason: str | None = None,
                               details: dict | None = None) -> SessionEvent:
    """Add the SessionEvent row (caller commits); emit an ECS line when ``action`` is set."""
    event = SessionEvent(instance_id=instance.id, event_type=event_type)
    if details is not None:
        event.details = details
    session.add(event)
    if action:
        owner = await session.get(User, instance.owner_id)
        names = (await session.exec(
            select(Group.name).join(UserGroup, col(UserGroup.group_id) == Group.id)
            .where(UserGroup.user_id == instance.owner_id).order_by(Group.name)
        )).all()
        emit(session_event(
            action, session_id=instance.id, kind="instance", user_id=instance.owner_id,
            user_name=owner.username if owner else None, reason=reason,
            image_digest=instance.image_digest,
            node=os.environ.get("NODE_NAME") or socket.gethostname(), groups=list(names)))
    return event
