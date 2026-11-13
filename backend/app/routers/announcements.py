"""Admin announcements + maintenance banner (styx-portal#299)."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import Announcement, User
from app.security.deps import get_current_user, require_admin
from app.services.audit import audit_request

admin_router = APIRouter()
router = APIRouter()

Kind = Literal["info", "maintenance"]


def _naive_utc(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


class _Window(BaseModel):
    @field_validator("starts_at", "ends_at", check_fields=False)
    @classmethod
    def _utc(cls, v):
        return _naive_utc(v)


class AnnouncementCreate(_Window):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    kind: Kind = "info"
    starts_at: datetime | None = None
    ends_at: datetime | None = None

    @model_validator(mode="after")
    def _order(self):
        if self.starts_at and self.ends_at and self.ends_at <= self.starts_at:
            raise ValueError("ends_at must be after starts_at")
        return self


class AnnouncementUpdate(_Window):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=2000)
    kind: Kind | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None


class AnnouncementOut(BaseModel):
    id: str
    title: str
    body: str
    kind: str
    starts_at: datetime
    ends_at: datetime | None
    created_by: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _get(session: AsyncSession, aid: str) -> Announcement:
    a = await session.get(Announcement, aid)
    if not a:
        raise HTTPException(404, "Announcement not found")
    return a


@admin_router.get("", response_model=list[AnnouncementOut])
async def list_announcements(admin: User = Depends(require_admin),
                             session: AsyncSession = Depends(get_session)):
    return (await session.exec(
        select(Announcement).order_by(Announcement.starts_at.desc()))).all()


@admin_router.post("", response_model=AnnouncementOut, status_code=201)
async def create_announcement(body: AnnouncementCreate, request: Request,
                              admin: User = Depends(require_admin),
                              session: AsyncSession = Depends(get_session)):
    data = body.model_dump(exclude_none=True)
    a = Announcement(**data, created_by=admin.id)
    session.add(a)
    await audit_request(session, request, "announcement.create", user_id=admin.id,
                        resource=a.id, detail={"kind": a.kind})
    await session.commit()
    return a


@admin_router.patch("/{aid}", response_model=AnnouncementOut)
async def update_announcement(aid: str, body: AnnouncementUpdate, request: Request,
                              admin: User = Depends(require_admin),
                              session: AsyncSession = Depends(get_session)):
    a = await _get(session, aid)
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k != "ends_at":
            continue
        setattr(a, k, v)
    if a.ends_at and a.ends_at <= a.starts_at:
        raise HTTPException(422, "ends_at must be after starts_at")
    session.add(a)
    await audit_request(session, request, "announcement.update", user_id=admin.id,
                        resource=a.id, detail={})
    await session.commit()
    return a


@admin_router.delete("/{aid}", status_code=204)
async def delete_announcement(aid: str, request: Request,
                              admin: User = Depends(require_admin),
                              session: AsyncSession = Depends(get_session)):
    a = await _get(session, aid)
    await session.delete(a)
    await audit_request(session, request, "announcement.delete", user_id=admin.id,
                        resource=aid, detail={})
    await session.commit()
    return Response(status_code=204)


@router.get("/active", response_model=list[AnnouncementOut])
async def active_announcements(user: User = Depends(get_current_user),
                               session: AsyncSession = Depends(get_session)):
    now = _now()
    rows = (await session.exec(
        select(Announcement).where(
            Announcement.starts_at <= now,
            (Announcement.ends_at.is_(None)) | (Announcement.ends_at > now))
        .order_by(Announcement.starts_at.desc()))).all()
    return sorted(rows, key=lambda a: a.kind != "maintenance")
