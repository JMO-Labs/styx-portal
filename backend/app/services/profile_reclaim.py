"""Leader-only reclaim of profiles unused for 60 d, after a 14 d notice (ADR-0035)."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Notice, UserProfile
from app.services.audit import audit
from app.services.notices import post_notice
from app.services.profiles import delete_profile, profile_in_use

log = logging.getLogger(__name__)
KIND = "profile_reclaim"
UNUSED = timedelta(days=60)
GRACE = timedelta(days=14)
INTERVAL_S = 86400


async def _notice(session, p: UserProfile) -> Notice | None:
    return (await session.exec(select(Notice).where(
        Notice.user_id == p.user_id, Notice.kind == KIND,
        Notice.key == p.volume_name))).first()


async def _reclaim(session, runtime, p: UserProfile, n: Notice, now: datetime) -> None:
    if await profile_in_use(session, p.volume_name):
        return
    user_id, template_id, volume = p.user_id, p.template_id, p.volume_name
    try:
        await delete_profile(session, runtime, user_id, template_id)
    except HTTPException as e:  # still referenced by an instance row: keep, retry next tick
        log.info("profile reclaim skipped for %s: %s", volume, e.detail)
        return
    n.dismissed_at = now
    session.add(n)
    await audit(session, "profile.reclaim", user_id=user_id, resource=template_id,
                detail={"volume": volume})
    await session.commit()


async def profile_reclaim_tick(session: AsyncSession, runtime, now: datetime,
                               is_leader=True) -> None:
    if not (is_leader() if callable(is_leader) else is_leader):
        return
    now = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
    for p in (await session.exec(select(UserProfile))).all():
        last = p.last_used_at or p.created_at
        n = await _notice(session, p)
        if n is not None and n.dismissed_at is None:
            noticed_at = n.due_at - GRACE if n.due_at is not None else n.created_at
            if last > noticed_at:  # used since the notice: keep it
                n.dismissed_at = now
                session.add(n)
                await session.commit()
            elif n.due_at is not None and n.due_at <= now:
                await _reclaim(session, runtime, p, n, now)
            continue
        if now - last <= UNUSED:
            continue
        if n is not None:  # earlier cycle was dismissed; stale again: fresh notice
            await session.delete(n)
            await session.commit()
        await post_notice(
            session, p.user_id, KIND, p.volume_name,
            "This persistent profile has been unused for 60 days and will be deleted "
            "in 14 days. Launch it to keep it.", now + GRACE)


async def profile_reclaim_loop(session_factory, runtime_factory, is_leader=True) -> None:
    while True:
        try:
            async with session_factory() as session:
                await profile_reclaim_tick(session, runtime_factory(), datetime.now(timezone.utc),
                                           is_leader)
        except Exception:  # noqa: BLE001 - keep the daily loop alive
            log.warning("profile reclaim pass failed", exc_info=True)
        await asyncio.sleep(INTERVAL_S)
