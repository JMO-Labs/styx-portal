"""Admin console read API: live sessions and capacity (ADR-0026 staff roles)."""
from collections import Counter

from fastapi import APIRouter, Depends
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import Instance, ServiceTemplate, StreamSession, User
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
         .join(ServiceTemplate, Instance.template_id == ServiceTemplate.id)
         .outerjoin(User, Instance.owner_id == User.id)
         .where(Instance.status == "running")
         .order_by(Instance.started_at))
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
        StreamSession.ended_at.is_(None)))).all())
    return {
        "running": len(rows),
        "max_per_user": settings.get("MAX_INSTANCES_PER_USER") or None,
        "limit": None,
        "live_streams": live,
        "per_node": dict(Counter(node or "unknown" for _ in rows)),
    }
