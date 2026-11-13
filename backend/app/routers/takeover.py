"""Session takeover start/end with mandatory reason and audit events (ADR-0060)."""
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import Instance, SessionTakeover, User
from app.security.deps import can_takeover, get_current_user, require_staff_role
from app.services import takeover_alert
from app.services.audit import audit_request
from app.services.takeover_report import build_report, month_bounds

router = APIRouter()
admin_router = APIRouter()
log = logging.getLogger("styx.takeover")
report_router = APIRouter()


class TakeoverIn(BaseModel):
    mode: Literal["view", "control"]
    reason: str

    @field_validator("reason")
    @classmethod
    def _reason(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("reason required")
        return v


class TakeoverOut(BaseModel):
    id: str
    instance_id: str
    mode: str
    reason: str
    started_at: datetime


class ActiveTakeoverOut(BaseModel):
    actor_name: str
    mode: str
    started_at: datetime


class TakeoverListOut(TakeoverOut):
    actor_id: str
    user_id: str | None = None
    ended_at: datetime | None = None


async def _gate(session: AsyncSession, request: Request, user: User, iid: str,
                action: str) -> Instance:
    inst = await session.get(Instance, iid)
    if not can_takeover(user):
        await audit_request(session, request, "takeover.denied", user_id=user.id,
                            resource=iid, detail={"attempted": action})
        await session.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Takeover not permitted")
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instance not found")
    return inst


async def _active(session: AsyncSession, iid: str) -> SessionTakeover | None:
    return (await session.exec(select(SessionTakeover).where(
        SessionTakeover.instance_id == iid, SessionTakeover.ended_at.is_(None)))).first()


def _detail(t: SessionTakeover) -> dict:
    return {"actor_id": t.actor_id, "user_id": t.user_id, "mode": t.mode, "reason": t.reason,
            "started_at": t.started_at.isoformat(),
            "ended_at": t.ended_at.isoformat() if t.ended_at else None}


@router.post("/{iid}/takeover", response_model=TakeoverOut, status_code=status.HTTP_201_CREATED)
async def start_takeover(iid: str, body: TakeoverIn, request: Request,
                         user: User = Depends(get_current_user),
                         session: AsyncSession = Depends(get_session)):
    inst = await _gate(session, request, user, iid, "start")
    conflict = HTTPException(status.HTTP_409_CONFLICT, "Takeover already active")
    if await _active(session, iid):
        raise conflict
    t = SessionTakeover(instance_id=iid, actor_id=user.id, user_id=inst.owner_id,
                        mode=body.mode, reason=body.reason)
    session.add(t)
    await audit_request(session, request, "takeover.start", user_id=user.id,
                        resource=iid, detail=_detail(t))
    try:
        await session.commit()
    except IntegrityError:  # lost a race against the partial unique index
        await session.rollback()
        raise conflict
    try:
        await takeover_alert.notify_start(t, Settings().MATRIX_SECURITY_WEBHOOK_URL)
    except Exception as e:  # noqa: BLE001 - alert must never fail the takeover
        log.warning("takeover alert failed: %s", type(e).__name__)
    return t


@router.delete("/{iid}/takeover", status_code=status.HTTP_204_NO_CONTENT)
async def end_takeover(iid: str, request: Request, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_session)):
    await _gate(session, request, user, iid, "end")
    t = await _active(session, iid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No active takeover")
    t.ended_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(t)
    await audit_request(session, request, "takeover.end", user_id=user.id,
                        resource=iid, detail=_detail(t))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{iid}/takeover", response_model=ActiveTakeoverOut | None)
async def get_takeover(iid: str, user: User = Depends(get_current_user),
                       session: AsyncSession = Depends(get_session)):
    """Active takeover for the session owner's banner; readable by owner and actor only."""
    inst = await session.get(Instance, iid)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Instance not found")
    t = await _active(session, iid)
    if user.id != inst.owner_id and not (t and t.actor_id == user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not permitted")
    if t is None:
        return None
    actor = await session.get(User, t.actor_id)
    name = actor.username if actor else "Support staff"
    return ActiveTakeoverOut(actor_name=name, mode=t.mode, started_at=t.started_at)


@admin_router.get("/takeovers", response_model=list[TakeoverListOut])
async def list_takeovers(since: datetime | None = None,
                         _: User = Depends(require_staff_role("platform-admin", "auditor")),
                         session: AsyncSession = Depends(get_session)):
    q = select(SessionTakeover).order_by(SessionTakeover.started_at.desc())
    if since is not None:
        q = q.where(SessionTakeover.started_at >= (since.astimezone(timezone.utc) if since.tzinfo else since).replace(tzinfo=None))
    return (await session.exec(q)).all()


@report_router.get("/report")
async def takeover_report(month: str, request: Request,
                          user: User = Depends(require_staff_role("platform-admin", "auditor")),
                          session: AsyncSession = Depends(get_session)):
    try:
        month_bounds(month)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "month must be YYYY-MM")
    body = await build_report(session, month)
    await audit_request(session, request, "takeover.report", user_id=user.id,
                        detail={"month": month})
    await session.commit()
    return Response(body, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="takeovers-{month}.csv"'})
