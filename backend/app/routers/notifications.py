from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import Notification, User
from app.security.deps import get_current_user, require_admin

router = APIRouter()
admin_router = APIRouter()
LIMIT = 50


class NotificationOut(BaseModel):
    id: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(max_length=2000)
    link: str | None = Field(default=None, max_length=500)
    user_id: str | None = None
    all: bool = False

    @model_validator(mode="after")
    def _one_target(self):
        if bool(self.user_id) == self.all:
            raise ValueError("Provide exactly one of user_id or all")
        return self


def _unread(user_id: str):
    return (Notification.user_id == user_id) & Notification.read_at.is_(None)


@router.get("")
async def list_notifications(user: User = Depends(get_current_user),
                             session: AsyncSession = Depends(get_session)):
    rows = (await session.exec(
        select(Notification).where(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc(), Notification.id).limit(LIMIT))).all()
    unread = (await session.exec(
        select(func.count()).select_from(Notification).where(_unread(user.id)))).one()
    return {"items": [NotificationOut.model_validate(n, from_attributes=True) for n in rows],
            "unread": unread}


@router.post("/read-all")
async def read_all(user: User = Depends(get_current_user),
                   session: AsyncSession = Depends(get_session)):
    res = await session.exec(update(Notification).where(_unread(user.id))
                             .values(read_at=datetime.now(timezone.utc)))
    await session.commit()
    return {"updated": res.rowcount}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: User = Depends(get_current_user),
                    session: AsyncSession = Depends(get_session)):
    n = await session.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    if n.read_at is None:
        n.read_at = datetime.now(timezone.utc)
        session.add(n)
        await session.commit()
    return {"id": n.id, "read_at": n.read_at}


@admin_router.post("", status_code=201)
async def send_notification(body: NotificationCreate,
                            admin: User = Depends(require_admin),
                            session: AsyncSession = Depends(get_session)):
    if body.all:
        ids = (await session.exec(select(User.id).where(User.is_active))).all()
    else:
        if await session.get(User, body.user_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
        ids = [body.user_id]
    session.add_all([Notification(user_id=i, title=body.title, body=body.body,
                                  link=body.link) for i in ids])
    await session.commit()
    return {"created": len(ids)}
