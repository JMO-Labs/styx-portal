"""Access-token jti denylist for hard kill-on-logout.

Access tokens are stateless and stay valid until exp; logout clears the cookie
but can't invalidate the token value. This denylist lets logout revoke a token
immediately — closing the replay window (notably the workstation stream
reconnect after logout). Entries only need to live until the token's own exp,
so the leader janitor purges them after that.
"""
from datetime import datetime, timezone

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import RevokedAccessToken


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def revoke_access(session: AsyncSession, jti: str, expires_at: datetime) -> None:
    """Add an access-token jti to the denylist (caller commits). Race-free upsert:
    concurrent or repeated calls for one jti never raise. Expired rows are purged
    by the leader janitor (app.services.janitor), not here."""
    if not jti:
        return
    bind = session.get_bind()
    insert = pg_insert if bind.dialect.name == "postgresql" else sqlite_insert
    exp = expires_at.replace(tzinfo=None) if expires_at.tzinfo else expires_at
    await session.exec(insert(RevokedAccessToken).values(jti=jti, expires_at=exp)
                       .on_conflict_do_nothing(index_elements=["jti"]))


async def is_access_revoked(session: AsyncSession, jti: str | None) -> bool:
    """True if this access-token jti has been revoked. Presence is revocation:
    expired entries are purged on write, and an expired token is rejected by
    decode_token before this is ever consulted — so no exp comparison here
    (which would also trip on SQLite's tz-naive datetimes)."""
    if not jti:
        return False
    return await session.get(RevokedAccessToken, jti) is not None
