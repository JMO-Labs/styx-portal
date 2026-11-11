"""Lockout gate, failure path and success clears shared by password and matrix login."""
import json
import logging
from datetime import timedelta

from fastapi import Request, Response
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import User
from app.security import tokens
from app.security.cookies import set_mfa_cookie
from app.services import matrix_card
from app.services import abuse_store
from app.services.abuse import ban_cache, ban_ip
from app.services.audit import audit_request
from app.services.settings_store import settings as sys_settings

_settings = Settings()
logger = logging.getLogger("styx-portal")


async def blocked(username: str, ip: str, rnd: str | None) -> bool:
    """Locked or throttled, unless a still-trusted device cookie for this account vouches.
    Fails closed: a store error denies."""
    try:
        st = abuse_store.get_abuse_store()
        if rnd is not None and not await st.device_blocked(rnd):
            return False
        return (await st.is_locked(username, ip)
                or await st.throttled(username, _settings.LOGIN_GLOBAL_THRESHOLD,
                                      sys_settings.get("LOCKOUT_DURATION")))
    except Exception:
        logger.exception("abuse store failed; denying login attempt")
        return True


async def locked(username: str, ip: str, rnd: str | None) -> bool:
    """Card step: the password step already passed the global throttle, so only the
    per-(user, IP) lock applies (re-spending the 10 s slot would refuse correct codes).
    Fails closed."""
    try:
        st = abuse_store.get_abuse_store()
        if rnd is not None and not await st.device_blocked(rnd):
            return False
        return await st.is_locked(username, ip)
    except Exception:
        logger.exception("abuse store failed; denying login attempt")
        return True


def session_only_expired(session_only: bool, age: timedelta) -> bool:
    """Absolute cap for session-only (card, public computer) refresh families."""
    return session_only and age > timedelta(hours=sys_settings.get("MATRIX_SESSION_MAX_HOURS"))


def session_ttl(session_only: bool) -> int:
    """Refresh/proxy token TTL (s); session-only families never outlive their cap."""
    ttl = sys_settings.get("REFRESH_TTL")
    return min(ttl, sys_settings.get("MATRIX_SESSION_MAX_HOURS") * 3600) if session_only else ttl


async def record_failure(session: AsyncSession, request: Request, *, username: str, ip: str,
                         resolved: bool, rnd: str | None, track_user: bool,
                         action: str, **audit) -> None:
    tripped = False
    # Store errors must not turn a failed login into a 500; the checks above fail closed.
    try:
        st = abuse_store.get_abuse_store()
        if rnd:
            await st.device_fail(rnd, sys_settings.get("LOCKOUT_THRESHOLD"),
                                 sys_settings.get("LOCKOUT_DURATION"))
        # Only real accounts are tracked (keeps the maps bounded by the user count).
        if track_user:
            await st.record_fail(username, ip, sys_settings.get("LOCKOUT_THRESHOLD"),
                                 sys_settings.get("LOCKOUT_DURATION"))
        # Per-IP abuse detector -> proxy ban (L3). Thresholds are live-tunable.
        # Unresolved: still tracked under the peer address, but a misconfiguration must
        # never persist a ban on the proxy itself (it would lock out the whole portal).
        tripped = await st.ip_fail(ip, sys_settings.get("BAN_FAIL_THRESHOLD"),
                                   sys_settings.get("BAN_FAIL_WINDOW"))
    except Exception:
        logger.exception("abuse store failed recording a login failure")
    if tripped and resolved:
        await ban_ip(session, ip, "brute-force: failed logins", sys_settings.get("BAN_DURATION"))
        ban_cache.invalidate()
    await audit_request(session, request, action, **audit)
    await session.commit()


async def clear_lockout(session: AsyncSession, user: User, ip: str, rnd: str | None) -> None:
    user.failed_count = 0
    user.locked_until = None
    try:
        st = abuse_store.get_abuse_store()
        await st.clear(user.username, ip)
        if rnd:
            await st.device_clear(rnd)    # the fresh device cookie carries a new rnd
    except Exception:
        logger.exception("abuse store failed clearing lockout")
    session.add(user)


async def start_matrix(session: AsyncSession, request: Request, response: Response,
                       user: User) -> dict:
    """Password passed for a card user: pin a challenge (stable until answered) and hand
    out the short-lived styx_mfa cookie. No session and no lockout clears yet."""
    if not user.matrix_challenge:
        user.matrix_challenge = json.dumps(matrix_card.pick_challenge())
        session.add(user)
    set_mfa_cookie(response, tokens.create_mfa_token(user.id, user.token_version,
                                                     user.matrix_serial))
    await audit_request(session, request, "auth.matrix_challenge", user_id=user.id)
    await session.commit()
    return {"mfa_required": True, "challenge": json.loads(user.matrix_challenge)}
