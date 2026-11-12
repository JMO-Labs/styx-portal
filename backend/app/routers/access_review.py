"""Quarterly access review: per-manager report, certify/revoke, CSV export (ADR-0024)."""
import csv
import io
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import AccessReviewDecision, Group, User, UserGroup
from app.security.deps import get_current_user
from app.services import kc_admin
from app.services.audit import audit_request

router = APIRouter()

_QUARTER = re.compile(r"^\d{4}-Q[1-4]$")


def _quarter(q: str) -> str:
    if not _QUARTER.match(q):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "quarter must look like 2026-Q4")
    return q


class DecisionIn(BaseModel):
    group_id: str
    user_id: str
    quarter: str
    decision: Literal["certify", "revoke"]


async def _managed_groups(session: AsyncSession, user: User) -> list[Group]:
    q = select(Group).order_by(Group.name)
    if user.role != "admin":
        q = q.where(Group.manager_user_id == user.id)
    groups = (await session.exec(q)).all()
    if not groups and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a group manager")
    return list(groups)


async def _rows(session: AsyncSession, user: User, quarter: str) -> list[dict]:
    groups = await _managed_groups(session, user)
    out: list[dict] = []
    for g in groups:
        members = (await session.exec(
            select(User).join(UserGroup, UserGroup.user_id == User.id)
            .where(UserGroup.group_id == g.id).order_by(User.username))).all()
        decided = {d.user_id: d for d in (await session.exec(
            select(AccessReviewDecision).where(
                AccessReviewDecision.group_id == g.id,
                AccessReviewDecision.quarter == quarter)
            .order_by(AccessReviewDecision.decided_at))).all()}
        actors = {}
        for u in members:
            d = decided.pop(u.id, None)
            out.append(await _row(session, actors, quarter, g, u.id, u.username, u.email, d))
        # Revoked members are no longer in the group: keep them in the report.
        for uid, d in decided.items():
            u = await session.get(User, uid)
            out.append(await _row(session, actors, quarter, g, uid,
                                  u.username if u else uid, u.email if u else None, d))
    return out


async def _row(session, actors: dict, quarter, g, uid, username, email, d) -> dict:
    actor = None
    if d:
        if d.actor_id not in actors:
            a = await session.get(User, d.actor_id)
            actors[d.actor_id] = a.username if a else d.actor_id
        actor = actors[d.actor_id]
    return {"quarter": quarter, "group_id": g.id, "group": g.name, "user_id": uid,
            "username": username, "email": email,
            "decision": d.decision if d else None, "actor": actor,
            "decided_at": d.decided_at.isoformat() if d else None}


@router.get("")
async def report(quarter: str = Query(...), user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_session)):
    return await _rows(session, user, _quarter(quarter))


@router.post("/decisions", status_code=201)
async def decide(body: DecisionIn, request: Request, user: User = Depends(get_current_user),
                 session: AsyncSession = Depends(get_session)):
    _quarter(body.quarter)
    g = await session.get(Group, body.group_id)
    if g is None or (user.role != "admin" and g.manager_user_id != user.id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not the manager of this group")
    link = await session.get(UserGroup, (body.user_id, g.id))
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User is not a member of this group")
    existing = (await session.exec(select(AccessReviewDecision).where(
        AccessReviewDecision.group_id == g.id, AccessReviewDecision.user_id == body.user_id,
        AccessReviewDecision.quarter == body.quarter))).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Already decided this quarter")
    session.add(AccessReviewDecision(group_id=g.id, user_id=body.user_id, quarter=body.quarter,
                                     decision=body.decision, actor_id=user.id))
    if body.decision == "revoke":
        await session.delete(link)
    await audit_request(session, request, f"access_review.{body.decision}", user_id=user.id,
                        resource=g.id, detail={"target_user": body.user_id,
                                               "quarter": body.quarter})
    await session.commit()
    if body.decision == "revoke" and g.kc_group_id:
        await kc_admin.remove_from_group(body.user_id, g.kc_group_id)
    return {"group_id": g.id, "user_id": body.user_id, "quarter": body.quarter,
            "decision": body.decision}


@router.get("/export.csv")
async def export_csv(quarter: str = Query(...), user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    rows = await _rows(session, user, _quarter(quarter))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["quarter", "group", "username", "email", "decision", "actor", "decided_at"])
    for r in rows:
        w.writerow([_safe(r[k] or "") for k in
                    ("quarter", "group", "username", "email", "decision", "actor", "decided_at")])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="access-review-{quarter}.csv"'})


def _safe(v: str) -> str:
    """Neutralise spreadsheet formula injection."""
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v
