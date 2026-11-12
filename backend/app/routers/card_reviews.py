"""Admin API: card-binding review queue (ADR-0016)."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, model_validator
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import ApprovedRequest, CardReview, User
from app.security.deps import require_admin
from app.services import card_binding
from app.services.audit import audit_request

router = APIRouter()


class Resolve(BaseModel):
    decision: Literal["approve", "reject"]
    request_id: str | None = None   # approved request to bind (required for approve)

    @model_validator(mode="after")
    def _need_request(self):
        if self.decision == "approve" and not self.request_id:
            raise ValueError("request_id required to approve")
        return self


def _row(c: CardReview) -> dict:  # claims (EDIPI / card id) are deliberately omitted
    return {"id": c.id, "kc_user_id": c.kc_user_id, "card_type": c.card_type,
            "reason": c.reason, "status": c.status, "created_at": c.created_at,
            "resolved_at": c.resolved_at}


@router.get("")
async def list_reviews(status: str = "pending", admin: User = Depends(require_admin),
                       session: AsyncSession = Depends(get_session)):
    q = select(CardReview).order_by(CardReview.created_at)
    if status != "all":
        q = q.where(CardReview.status == status)
    return [_row(c) for c in (await session.exec(q)).all()]


@router.post("/{review_id}/resolve")
async def resolve(review_id: str, body: Resolve, request: Request,
                  admin: User = Depends(require_admin),
                  session: AsyncSession = Depends(get_session)):
    item = await session.get(CardReview, review_id)
    if not item:
        raise HTTPException(404, "Review not found")
    if item.status != "pending":
        raise HTTPException(409, "Already resolved")
    if body.decision == "approve":
        ar = await session.get(ApprovedRequest, body.request_id)
        if not ar or ar.status != card_binding.PENDING:
            raise HTTPException(409, "Request not awaiting binding")
        if not item.kc_user_id:
            raise HTTPException(409, "Review has no Keycloak user")
        claims = {**item.claims, "card_type": item.card_type}
        if card_binding.card_key(claims) is None:
            raise HTTPException(409, "Card claims incomplete")
        await card_binding.bind(session, item.kc_user_id, ar, claims,
                                action="card.review.bound", actor=admin.id, commit=False)
    item.status = "approved" if body.decision == "approve" else "rejected"
    item.resolved_by = admin.id
    item.resolved_at = datetime.now(timezone.utc)
    session.add(item)
    await audit_request(session, request, f"card.review.{item.status}", user_id=admin.id,
                        resource=item.id, detail={"card_type": item.card_type})
    await session.commit()
    return _row(item)
