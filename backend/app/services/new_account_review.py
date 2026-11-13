"""New-account review (ADR-0023): auto-suspend accounts left unreviewed."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import User
from app.services.offboarding import disable_account

log = logging.getLogger(__name__)
MAX_BUSINESS_DAYS = 2
INTERVAL_S = 3600


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def business_days_between(a: datetime, b: datetime) -> int:
    """Whole Mon-Fri days after ``a``'s date up to and including ``b``'s date (weekends skipped)."""
    start, end = _utc(a).date(), _utc(b).date()
    n, d = 0, start
    while d < end:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


async def review_pass(session: AsyncSession, now: datetime | None = None) -> int:
    """Suspend unreviewed users older than 2 business days; returns how many. Idempotent."""
    now = now or datetime.now(timezone.utc)
    users = (await session.exec(select(User).where(
        col(User.reviewed_at).is_(None), col(User.disabled_at).is_(None)))).all()
    n = 0
    for u in users:
        if business_days_between(u.created_at, now) > MAX_BUSINESS_DAYS:
            if await disable_account(session, u, "unreviewed", actor=None):
                n += 1
    return n


async def new_account_review_loop(session_factory) -> None:
    """Leader-only loop: register with the leader task set (runs on one replica)."""
    while True:
        try:
            async with session_factory() as s:
                n = await review_pass(s)
                if n:
                    log.warning("auto-suspended %d unreviewed account(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep the loop alive
            log.exception("new-account review pass failed")
        await asyncio.sleep(INTERVAL_S)
