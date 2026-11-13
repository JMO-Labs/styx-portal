"""Delete accounts ACCOUNT_DELETION_RETENTION_DAYS (default 90) after disable (ADR-0022).

Removes the home volume(s) and Keycloak user, then the Styx user. Leader-only:
the caller schedules it on the elected leader. Idempotent; 404 counts as done.
"""
import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import (FederatedIdentity, Instance, Invite, RefreshToken,
                        ServiceTemplate, SessionEvent, TurnUsage, User, UserGroup,
                        UserProfile, Workstation, WorkstationAccess,
                        WorkstationEnrollmentToken)
from app.services import kc_admin
from app.services.audit import audit

log = logging.getLogger(__name__)
RETENTION_DAYS = 90
INTERVAL_S = 3600


def _is_404(exc: Exception) -> bool:
    code = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None)
    return code == 404 or type(exc).__name__ == "NotFound"


# Non-null / ownership references: reassigned to an admin (NULL template owner = global).
_REASSIGN = ((ServiceTemplate, "owner_id"), (Invite, "created_by"),
             (Workstation, "created_by"), (WorkstationEnrollmentToken, "created_by"))


async def _detach_references(session: AsyncSession, uid: str) -> None:
    """Remove or reassign every other row that references users.id."""
    await session.exec(delete(UserGroup).where(col(UserGroup.user_id) == uid))
    await session.exec(delete(WorkstationAccess).where(col(WorkstationAccess.user_id) == uid))
    await session.exec(update(TurnUsage).where(col(TurnUsage.user_id) == uid).values(user_id=None))
    await session.exec(update(Workstation).where(col(Workstation.occupied_by) == uid)
                       .values(occupied_by=None))
    admin_id = (await session.exec(select(User.id).where(
        col(User.role) == "admin", col(User.id) != uid).order_by(col(User.created_at)))).first()
    for model, attr in _REASSIGN:
        c = getattr(model, attr)
        if admin_id is None:
            if (await session.exec(select(c).where(c == uid))).first() is not None:
                raise RuntimeError(f"no admin to take over {model.__tablename__}.{attr}")
            continue
        await session.exec(update(model).where(c == uid).values({attr: admin_id}))


async def _delete_one(session: AsyncSession, user: User, runtime,
                      kc_delete: Callable[[str], Awaitable[None]], kc_provider: str) -> None:
    profiles = (await session.exec(select(UserProfile).where(UserProfile.user_id == user.id))).all()
    for p in profiles:
        try:
            await asyncio.to_thread(runtime.remove_volume, p.volume_name)
        except Exception as e:  # noqa: BLE001
            if not _is_404(e):
                raise
    idents = (await session.exec(select(FederatedIdentity).where(
        FederatedIdentity.user_id == user.id,
        FederatedIdentity.provider == kc_provider))).all()
    for i in idents:
        try:
            await kc_delete(i.subject)
        except Exception as e:  # noqa: BLE001
            if not _is_404(e):
                raise
    ids = (await session.exec(select(Instance.id).where(Instance.owner_id == user.id))).all()
    if ids:
        await session.exec(delete(SessionEvent).where(col(SessionEvent.instance_id).in_(ids)))
        await session.exec(delete(Instance).where(col(Instance.id).in_(ids)))
    await session.exec(delete(UserProfile).where(col(UserProfile.user_id) == user.id))
    await session.exec(delete(FederatedIdentity).where(col(FederatedIdentity.user_id) == user.id))
    await session.exec(delete(RefreshToken).where(col(RefreshToken.user_id) == user.id))
    await _detach_references(session, user.id)
    await audit(session, "account.deleted", resource=user.id,
                detail={"username": user.username, "user_id": user.id})
    await session.delete(user)
    await session.commit()


async def run_deletion_pass(session: AsyncSession, now: datetime, *, runtime=None,
                            kc_delete=None, retention_days: int = RETENTION_DAYS,
                            kc_provider: str | None = None) -> int:
    """Delete users disabled >= ``retention_days`` ago; returns how many were deleted."""
    cutoff = now - timedelta(days=retention_days)
    users = (await session.exec(select(User).where(
        col(User.disabled_at).is_not(None), col(User.disabled_at) <= cutoff,
        User.is_active == False))).all()  # noqa: E712  re-enabled users are active
    if users and runtime is None:
        from app.services.k8s_runtime import instance_runtime
        runtime = instance_runtime()
    kc_delete = kc_delete or kc_admin.delete_user
    kc_provider = kc_provider or Settings().KC_PROVIDER_NAME
    done = 0
    for user in list(users):
        uid = user.id  # read before rollback expires the instance
        try:
            await _delete_one(session, user, runtime, kc_delete, kc_provider)
            done += 1
        except Exception:  # noqa: BLE001  keep the user; next pass retries
            await session.rollback()
            log.exception("account deletion failed for user %s", uid)
    return done


async def account_deletion_loop(session_factory) -> None:
    """Leader-only loop: registered in main.py's leader_loops (one replica runs it)."""
    while True:
        try:
            cfg = Settings()
            async with session_factory() as s:
                n = await run_deletion_pass(
                    s, datetime.now(timezone.utc),
                    retention_days=cfg.ACCOUNT_DELETION_RETENTION_DAYS,
                    kc_provider=cfg.KC_PROVIDER_NAME)
                if n:
                    log.warning("deleted %d expired disabled account(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("account deletion pass failed")
        await asyncio.sleep(INTERVAL_S)
