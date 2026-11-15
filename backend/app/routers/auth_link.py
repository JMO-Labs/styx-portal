"""SSO account linking routes (split from auth.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import User, OAuthProvider, FederatedIdentity
from app.schemas import ConnectedIdentity
from app.security import oauth
from app.security.cookies import TX_PATH
from app.security.deps import get_current_user
from app.services import federation
from app.services.audit import audit_request

router = APIRouter()
_settings = Settings()


@router.get("/link/providers", response_model=list[ConnectedIdentity])
async def linked_providers(user: User = Depends(get_current_user),
                           session: AsyncSession = Depends(get_session)):
    rows = (await session.exec(select(FederatedIdentity).where(
        FederatedIdentity.user_id == user.id))).all()
    return [ConnectedIdentity(provider=r.provider, email=r.email,
                              created_at=r.created_at.isoformat()) for r in rows]


@router.get("/link/{name}/start")
async def link_start(name: str, user: User = Depends(get_current_user),
                     session: AsyncSession = Depends(get_session)):
    provider = (await session.exec(select(OAuthProvider).where(
        OAuthProvider.name == name, OAuthProvider.enabled == True))).first()  # noqa: E712
    if not provider:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown provider")
    url, state, verifier = await oauth.build_authorize(provider, mode="link")
    resp = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    resp.set_cookie(oauth.TX_COOKIE, oauth.pack_tx(name, state, verifier, "link", user.id),
                    max_age=oauth.TX_TTL, httponly=True,
                    secure=_settings.COOKIE_SECURE, samesite="lax", path=TX_PATH)
    return resp


def _link_redirect(code: str) -> RedirectResponse:
    resp = RedirectResponse(f"/?link={code}", status_code=302)
    resp.delete_cookie(oauth.TX_COOKIE, path=TX_PATH)
    return resp


@router.get("/link/{name}/callback")
async def link_callback(name: str, request: Request,
                        user: User = Depends(get_current_user),
                        session: AsyncSession = Depends(get_session)):
    tx_raw = request.cookies.get(oauth.TX_COOKIE)
    if not tx_raw:
        return _link_redirect("missing_state")
    try:
        tx = oauth.unpack_tx(tx_raw)
    except Exception:
        return _link_redirect("bad_state")
    if tx["provider"] != name or tx["mode"] != "link" or \
            request.query_params.get("state") != tx["state"]:
        return _link_redirect("bad_state")
    if tx["uid"] != user.id:
        return _link_redirect("error")
    provider = (await session.exec(select(OAuthProvider).where(
        OAuthProvider.name == name))).first()
    if not provider:
        return _link_redirect("error")
    try:
        identity = await oauth.fetch_identity(provider, "link", str(request.url), tx["verifier"])
        await federation.link_identity(session, user, name, identity)
        await audit_request(session, request, "sso.link", user_id=user.id,
                            resource=name, detail={"email": identity.email})
        await session.commit()
    except federation.FederationError:
        return _link_redirect("conflict")
    except Exception:
        return _link_redirect("error")
    return _link_redirect("ok")


@router.delete("/link/{name}")
async def unlink_provider(name: str, request: Request, user: User = Depends(get_current_user),
                          session: AsyncSession = Depends(get_session)):
    rows = (await session.exec(select(FederatedIdentity).where(
        FederatedIdentity.user_id == user.id))).all()
    target = next((r for r in rows if r.provider == name), None)
    if not target:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not linked")
    has_password = user.password_hash and not user.password_hash.startswith("!")
    if not has_password and len(rows) <= 1:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "cannot unlink the only login method")
    await session.delete(target)
    await audit_request(session, request, "sso.unlink", user_id=user.id, resource=name)
    await session.commit()
    return {"ok": True}
