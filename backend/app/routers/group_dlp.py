# backend/app/routers/group_dlp.py
"""Admin API for per-group DLP overrides (ADR-0038 amendment)."""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import Group, User
from app.schemas_group_dlp import GroupDlpOut, GroupDlpPut
from app.security.deps import require_admin
from app.services.audit import audit_request
from app.services.group_dlp import DLP_DEFAULTS, resolve_group_dlp

router = APIRouter()


def _override(g: Group) -> dict[str, bool | None]:
    return {k: getattr(g, f"dlp_{k}") for k in DLP_DEFAULTS}


def _out(g: Group) -> GroupDlpOut:
    return GroupDlpOut(override=_override(g), approval_ref=g.dlp_approval_ref,
                       approved_at=g.dlp_approved_at, effective=resolve_group_dlp([g]))


async def _group(session: AsyncSession, group_id: str) -> Group:
    g = await session.get(Group, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return g


@router.get("/{group_id}/dlp", response_model=GroupDlpOut)
async def get_group_dlp(group_id: str, admin: User = Depends(require_admin),
                        session: AsyncSession = Depends(get_session)):
    return _out(await _group(session, group_id))


@router.put("/{group_id}/dlp", response_model=GroupDlpOut)
async def put_group_dlp(group_id: str, body: GroupDlpPut, request: Request,
                        admin: User = Depends(require_admin),
                        session: AsyncSession = Depends(get_session)):
    g = await _group(session, group_id)
    old = _override(g)
    new = {k: getattr(body, k) for k in DLP_DEFAULTS}
    for k, v in new.items():
        setattr(g, f"dlp_{k}", v)
    g.dlp_approval_ref = body.approval_ref
    g.dlp_approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    session.add(g)
    await audit_request(session, request, "group.dlp_override", user_id=admin.id,
                        resource=g.id, detail={"old": old, "new": new,
                                               "approval_ref": body.approval_ref})
    await session.commit()
    return _out(g)


@router.delete("/{group_id}/dlp", response_model=GroupDlpOut)
async def delete_group_dlp(group_id: str, request: Request,
                           admin: User = Depends(require_admin),
                           session: AsyncSession = Depends(get_session)):
    g = await _group(session, group_id)
    old = _override(g)
    for k in DLP_DEFAULTS:
        setattr(g, f"dlp_{k}", None)
    old_ref = g.dlp_approval_ref
    g.dlp_approval_ref = None
    g.dlp_approved_at = None
    session.add(g)
    await audit_request(session, request, "group.dlp_override_remove", user_id=admin.id,
                        resource=g.id, detail={"old": old, "approval_ref": old_ref})
    await session.commit()
    return _out(g)
