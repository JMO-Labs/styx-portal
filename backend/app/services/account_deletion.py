"""Delete accounts RETENTION_DAYS after disable (ADR-0022).

Removes the home volume(s) and Keycloak user, then the Styx user. Leader-only:
the caller schedules it on the elected leader. Idempotent; 404 counts as done.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (FederatedIdentity, Instance, RefreshToken, SessionEvent,
                        User, UserProfile)
from app.services import kc_admin
from app.services.audit import audit

log = logging.getLogger(__name__)
RETENTION_DAYS = 90
INTERVAL_S = 3600


def _is_404(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None)
    return code == 404 or type(exc).__name__ == "NotFound"


async def _delete_one(session: AsyncSession, user: User, runtime,
                      kc_delete: Callable[[str], Awaitable[None]]) -> None:
    profiles = (await session.exec(select(UserProfile).where(UserProfile.user_id == user.id))).all()
    for p in profiles:
        try:
            await asyncio.to_thread(runtime.remove_volume, p.volume_name)
        except Exception as e:  # noqa: BLE001
            if not _is_404(e):
                raise
    idents = (await session.exec(select(FederatedIdentity).where(
        FederatedIdentity.user_id == user.id))).all()
    for i in idents:
        try:
            await kc_delete(i.subject)
        except Exception as e:  # noqa: BLE001
            if not _is_404(e):
                raise
    ids = (await session.exec(select(Instance.id).where(Instance.owner_id == user.id))).all()
    if ids:
        await session.exec(delete(SessionEvent).where(SessionEvent.instance_id.in_(ids)))
        await session.exec(delete(Instance).where(Instance.id.in_(ids)))
    await session.exec(delete(UserProfile).where(UserProfile.user_id == user.id))
    await session.exec(delete(FederatedIdentity).where(FederatedIdentity.user_id == user.id))
    await session.exec(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await audit(session, "account.deleted", resource=user.id,
                detail={"username": user.username, "user_id": user.id})
    await session.delete(user)
    await session.commit()


async def run_deletion_pass(session: AsyncSession, now: datetime, *, runtime=None,
                            kc_delete=None, retention_days: int = RETENTION_DAYS) -> int:
    """Delete users disabled >= ``retention_days`` ago; returns how many were deleted."""
    cutoff = now - timedelta(days=retention_days)
    users = (await session.exec(select(User).where(
        User.disabled_at.is_not(None), User.disabled_at <= cutoff,
        User.is_active == False))).all()  # noqa: E712  re-enabled users are active
    if users and runtime is None:
        from app.services.k8s_runtime import instance_runtime
        runtime = instance_runtime()
    kc_delete = kc_delete or kc_admin.delete_user
    done = 0
    for user in list(users):
        uid = user.id  # read before rollback expires the instance
        try:
            await _delete_one(session, user, runtime, kc_delete)
            done += 1
        except Exception:  # noqa: BLE001  keep the user; next pass retries
            await session.rollback()
            log.exception("account deletion failed for user %s", uid)
    return done


async def account_deletion_loop(session_factory) -> None:
    """Leader-only loop: registered in main.py's leader_loops (one replica runs it)."""
    while True:
        try:
            async with session_factory() as s:
                n = await run_deletion_pass(s, datetime.now(timezone.utc))
                if n:
                    log.warning("deleted %d expired disabled account(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("account deletion pass failed")
        await asyncio.sleep(INTERVAL_S)
