"""Per-session one-time smart-card relay tokens (ADR-0041). Only a SHA-256 hash is stored."""
import hashlib
import secrets
from datetime import timedelta, timezone

from sqlalchemy import update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import SmartcardToken, User, _now

TTL_S = 120


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def mint(session: AsyncSession, user_id: str, instance_id: str) -> str:
    token = secrets.token_urlsafe(32)
    session.add(SmartcardToken(token_hash=_hash(token), user_id=user_id, instance_id=instance_id,
                               expires_at=_now() + timedelta(seconds=TTL_S)))
    return token


async def redeem(session: AsyncSession, token: str, instance_id: str,
                 cert_username: str) -> tuple[SmartcardToken | None, str | None]:
    """Return (row, None) on success or (row-or-None, reason). Checks run before the token is
    consumed so a mismatched attempt cannot burn it; the consume itself is one atomic UPDATE."""
    row = (await session.exec(select(SmartcardToken).where(
        SmartcardToken.token_hash == _hash(token)))).first()
    if row is None:
        return None, "unknown"
    if row.used_at is not None:
        return row, "used"
    if row.expires_at.replace(tzinfo=timezone.utc) <= _now():
        return row, "expired"
    if row.instance_id != instance_id:
        return row, "instance_mismatch"
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active or not secrets.compare_digest(
            user.username.encode(), cert_username.encode()):
        return row, "cert_user_mismatch"
    res = await session.exec(update(SmartcardToken).where(
        SmartcardToken.id == row.id, col(SmartcardToken.used_at).is_(None)).values(used_at=_now()))
    if res.rowcount != 1:
        return row, "used"
    return row, None
