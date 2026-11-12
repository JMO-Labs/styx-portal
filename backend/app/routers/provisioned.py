"""Admin API: recently provisioned accounts, review and one-click suspend (ADR-0023)."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import User
from app.security.deps import require_admin
from app.services.audit import audit
from app.services.offboarding import disable_account

router = APIRouter()


def _row(u: User) -> dict:
    return {"id": u.id, "username": u.username, "email": u.email,
            "created_at": u.created_at, "reviewed_at": u.reviewed_at,
            "status": "disabled" if u.disabled_at else "active",
            "disabled_reason": u.disabled_reason}


async def _get(session: AsyncSession, uid: str) -> User:
    u = await session.get(User, uid)
    if not u:
        raise HTTPException(404, "User not found")
    return u


@router.get("")
async def list_provisioned(days: int = Query(14, ge=1, le=365),
                           admin: User = Depends(require_admin),
                           session: AsyncSession = Depends(get_session)):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = (await session.exec(select(User).where(User.created_at >= since)
                               .order_by(User.created_at.desc()))).all()
    return [_row(u) for u in rows]


@router.post("/{user_id}/review")
async def mark_reviewed(user_id: str, admin: User = Depends(require_admin),
                        session: AsyncSession = Depends(get_session)):
    u = await _get(session, user_id)
    u.reviewed_at = datetime.now(timezone.utc)
    session.add(u)
    await audit(session, "account.reviewed", user_id=admin.id, resource=u.id)
    await session.commit()
    return _row(u)


@router.post("/{user_id}/suspend")
async def suspend(user_id: str, admin: User = Depends(require_admin),
                  session: AsyncSession = Depends(get_session)):
    u = await _get(session, user_id)
    await disable_account(session, u, "new_account_suspend", actor=admin.id)
    return _row(u)
