"""Daily account lifecycle pass (ADR-0022): end-date and inactivity disable."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import FederatedIdentity, User
from app.services import kc_admin
from app.services.offboarding import disable_account

log = logging.getLogger(__name__)
DAY_S = 86400


def is_leader() -> bool:
    """Leader gate hook; always true on single-node SQLite."""
    return True


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _reason(u: User, now: datetime, cutoff: datetime) -> str | None:
    if u.end_date is not None and _utc(u.end_date) <= now:
        return "end_date"
    if u.role != "admin" and _utc(u.last_login or u.created_at) < cutoff:
        return "inactivity"
    return None


async def run_lifecycle_pass(session: AsyncSession, now: datetime,
                             inactivity_days: int | None = None) -> int:
    """Disable due accounts; returns how many were disabled this pass."""
    days = inactivity_days if inactivity_days is not None else Settings().LIFECYCLE_INACTIVITY_DAYS
    cutoff = now - timedelta(days=days)
    users = (await session.exec(select(User).where(
        col(User.is_active).is_(True), col(User.disabled_at).is_(None)))).all()
    count = 0
    for u in users:
        reason = _reason(u, now, cutoff)
        if reason is None:
            continue
        uid = u.id
        if not await disable_account(session, u, reason, None):
            continue
        count += 1
        subjects = (await session.exec(select(FederatedIdentity.subject).where(
            FederatedIdentity.user_id == uid))).all()
        for sub in subjects:
            try:
                await kc_admin.disable_user(sub)
            except Exception:  # noqa: BLE001 - local disable already took effect
                log.warning("lifecycle: keycloak disable failed for %s", uid, exc_info=True)
    return count


async def lifecycle_tick(session: AsyncSession, now: datetime, is_leader=is_leader) -> int:
    if not is_leader():
        return 0
    return await run_lifecycle_pass(session, now)


async def lifecycle_loop(session_factory) -> None:
    while True:
        try:
            async with session_factory() as session:
                await lifecycle_tick(session, datetime.now(timezone.utc))
        except Exception:  # noqa: BLE001 - keep the daily loop alive
            log.warning("lifecycle pass failed", exc_info=True)
        await asyncio.sleep(DAY_S)
