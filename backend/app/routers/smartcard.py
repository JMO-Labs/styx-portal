"""Smart-card relay tokens: owner mints (cookie auth); in-desktop relay redeems (shared secret)."""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import Instance, User
from app.security.deps import get_current_user
from app.services import smartcard_tokens as svc
from app.services.audit import audit_request

mint_router = APIRouter()
router = APIRouter()

RELAY_HEADER = "X-Relay-Secret"


class RedeemIn(BaseModel):
    token: str
    instance_id: str
    cert_username: str  # identity from the relay-verified client certificate


@mint_router.post("/{instance_id}/smartcard-token")
async def mint_token(instance_id: str, request: Request,
                     session: AsyncSession = Depends(get_session),
                     user: User = Depends(get_current_user)):
    inst = await session.get(Instance, instance_id)
    # Owner only, admins included: the card is bound to the user's own session.
    if not inst or inst.owner_id != user.id:
        raise HTTPException(404, "Instance not found")
    token = await svc.mint(session, user.id, instance_id)
    await audit_request(session, request, "smartcard.token.mint", user_id=user.id,
                        resource=instance_id)
    await session.commit()
    return {"token": token, "expires_in": svc.TTL_S}


@router.post("/redeem")
async def redeem_token(body: RedeemIn, request: Request,
                       session: AsyncSession = Depends(get_session)):
    expected = Settings().SMARTCARD_RELAY_SECRET
    given = request.headers.get(RELAY_HEADER, "")
    if not expected or not secrets.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(403, "Forbidden")
    row, reason = await svc.redeem(session, body.token, body.instance_id, body.cert_username)
    uid = row.user_id if row else None
    if reason:
        await audit_request(session, request, "smartcard.redeem.fail", user_id=uid,
                            resource=body.instance_id, detail={"reason": reason})
        await session.commit()
        raise HTTPException(403, "Invalid token")
    await audit_request(session, request, "smartcard.redeem.ok", user_id=uid,
                        resource=body.instance_id)
    await session.commit()
    return {"user_id": uid, "instance_id": body.instance_id}
