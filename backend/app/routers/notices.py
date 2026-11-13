from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import Notice, User
from app.security.deps import get_current_user

router = APIRouter()


def _out(n: Notice) -> dict:
    return {"id": n.id, "kind": n.kind, "key": n.key, "message": n.message,
            "due_at": n.due_at, "created_at": n.created_at}


@router.get("")
async def list_notices(session: AsyncSession = Depends(get_session),
                       user: User = Depends(get_current_user)):
    rows = (await session.exec(select(Notice).where(
        Notice.user_id == user.id, col(Notice.dismissed_at).is_(None))
        .order_by(col(Notice.created_at)))).all()
    return [_out(n) for n in rows]


@router.post("/{notice_id}/dismiss")
async def dismiss_notice(notice_id: str, session: AsyncSession = Depends(get_session),
                         user: User = Depends(get_current_user)):
    n = await session.get(Notice, notice_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(404, "Notice not found")
    if n.dismissed_at is None:
        n.dismissed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        session.add(n)
        await session.commit()
    return {"ok": True}
