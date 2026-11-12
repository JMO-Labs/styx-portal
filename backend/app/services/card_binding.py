"""First-login card binding (ADR-0016 / D16).

Exact key match only: CAC EDIPI == request EDIPI; PIV/PIV-I cert email == request email
(case-insensitive). Anything else (none, partial, name-only, several) goes to the admin
review queue. EDIPI and card UUID are never logged or put in audit detail.
"""
from sqlmodel import select

from app.models import ApprovedRequest, CardReview
from app.services import kc_admin
from app.services.audit import audit

PENDING = "pending_binding"
_PIV = {"PIV", "PIV-I"}


def _norm(v) -> str:
    return v.strip().lower() if isinstance(v, str) else ""


def card_key(claims: dict) -> tuple[str, str] | None:
    """(keycloak attribute, value) for the card, or None when claims lack it."""
    if claims.get("card_type") == "CAC":
        v = claims.get("edipi")
        return ("edipi", v) if v else None
    if claims.get("card_type") in _PIV:
        v = claims.get("card_id")
        return ("card_uuid", v) if v else None
    return None


def _matches(row: ApprovedRequest, claims: dict) -> bool:
    subj = row.subject or {}
    if claims["card_type"] == "CAC":
        return row.card_type == "CAC" and bool(claims.get("edipi")) \
            and subj.get("edipi") == claims["edipi"]
    return row.card_type == claims["card_type"] and bool(_norm(claims.get("cert_email"))) \
        and _norm(subj.get("email")) == _norm(claims["cert_email"])


async def bind(session, kc_user_id: str, row: ApprovedRequest, claims: dict,
               action: str = "card.bound", actor: str | None = None,
               commit: bool = True) -> None:
    """Bind the card to the user. Keycloak replaces the whole attribute map on PUT,
    so merge into the current map. commit=False lets the caller commit once."""
    key = card_key(claims)
    attrs = await kc_admin.get_attributes(kc_user_id)
    await kc_admin.set_attributes(kc_user_id, {**attrs, key[0]: [key[1]]})
    row.status = "bound"
    session.add(row)
    await audit(session, action, user_id=actor, resource=row.id,
                detail={"card_type": claims["card_type"], "kc_user_id": kc_user_id})
    if commit:
        await session.commit()


async def bind_card(session, claims: dict) -> str:
    """Returns "bound" or "queued". claims: sub, card_type, edipi | cert_email + card_id."""
    kc_user_id = claims.get("sub") or ""
    reason = "no_match"
    matches: list[ApprovedRequest] = []
    if not kc_user_id or card_key(claims) is None:
        reason = "invalid_claims"
    else:
        rows = (await session.exec(select(ApprovedRequest)
                                   .where(ApprovedRequest.status == PENDING))).all()
        matches = [r for r in rows if _matches(r, claims)]
        if len(matches) > 1:
            reason = "multiple_matches"
    if len(matches) == 1:
        await bind(session, kc_user_id, matches[0], claims)
        return "bound"
    keep = {k: claims[k] for k in ("edipi", "cert_email", "card_id") if claims.get(k)}
    item = CardReview(kc_user_id=kc_user_id, card_type=str(claims.get("card_type")),
                      claims=keep, reason=reason)
    session.add(item)
    await audit(session, "card.review.queued", resource=item.id,
                detail={"card_type": item.card_type, "reason": reason})
    await session.commit()
    return "queued"
