"""Admin console read API: live sessions and capacity (ADR-0026 staff roles)."""
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import Group, Instance, ServiceTemplate, StreamSession, User, UserGroup
from app.routers.me_storage import user_storage
from app.security.deps import require_staff_role
from app.services.settings_store import settings

router = APIRouter()
staff = require_staff_role("platform-admin", "help-desk", "auditor")


def _node() -> str | None:
    """Docker runs instances on the portal host ("local"); k8s pod placement is not
    persisted yet, so it is reported as unknown (None)."""
    return None if Settings().ROUTE_BACKEND == "k8s" else "local"


async def _running(session: AsyncSession):
    q = (select(Instance, ServiceTemplate, User)
         .join(ServiceTemplate, col(Instance.template_id) == ServiceTemplate.id)
         .outerjoin(User, col(Instance.owner_id) == User.id)
         .where(Instance.status == "running")
         .order_by(col(Instance.started_at)))
    return (await session.exec(q)).all()


@router.get("/sessions")
async def sessions(user: User = Depends(staff), session: AsyncSession = Depends(get_session)):
    node = _node()
    return {"sessions": [{
        "id": inst.id,
        "owner": owner.username if owner else None,
        "template": tpl.name,
        "image": inst.image_digest or tpl.image,
        "started_at": inst.started_at.isoformat() if inst.started_at else None,
        "node": node,
    } for inst, tpl, owner in await _running(session)]}


@router.get("/capacity")
async def capacity(user: User = Depends(staff), session: AsyncSession = Depends(get_session)):
    rows = await _running(session)
    node = _node()
    live = len((await session.exec(select(StreamSession.id).where(
        col(StreamSession.ended_at).is_(None)))).all())
    return {
        "running": len(rows),
        "max_per_user": settings.get("MAX_INSTANCES_PER_USER") or None,
        "limit": None,
        "live_streams": live,
        "per_node": dict(Counter(node or "unknown" for _ in rows)),
    }


@router.get("/users/{user_id}")
async def user_detail(user_id: str, user: User = Depends(staff),
                      session: AsyncSession = Depends(get_session)):
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(404, "User not found")
    groups = (await session.exec(select(Group.name).join(
        UserGroup, col(UserGroup.group_id) == Group.id).where(
        UserGroup.user_id == target.id).order_by(Group.name))).all()
    node = _node()
    running = [r for r in await _running(session) if r[0].owner_id == target.id]
    return {
        "id": target.id,
        "username": target.username,
        "display_name": target.username,  # no separate display-name column exists
        "email": target.email,
        "staff_role": target.staff_role,
        "groups": list(groups),
        "created_at": target.created_at.isoformat() if target.created_at else None,
        "last_login": target.last_login.isoformat() if target.last_login else None,
        "storage": await user_storage(session, target.id),
        "sessions": [{
            "id": inst.id, "template": tpl.name,
            "started_at": inst.started_at.isoformat() if inst.started_at else None,
            "node": node,
        } for inst, tpl, _ in running],
    }
