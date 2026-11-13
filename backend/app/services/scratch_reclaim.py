"""Reclaim per-instance scratch volumes 7 d after stop, with a notice (ADR-0035).

Leader-only. Only ``Instance.volume_names`` is touched, never the profile volume.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Instance
from app.services.account_deletion import _is_404
from app.services.audit import audit
from app.services.notices import post_notice

log = logging.getLogger(__name__)
RETENTION = timedelta(days=7)
INTERVAL_S = 3600
MESSAGE = ("Scratch storage for stopped instance '{name}' was reclaimed after 7 days. "
           "Keep persistent data in your home/profile volume.")


async def scratch_reclaim_tick(session: AsyncSession, runtime, now: datetime,
                               is_leader: bool) -> int:
    """Reclaim scratch volumes of instances stopped > 7 d; returns instances reclaimed."""
    if not is_leader:
        return 0
    now = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now
    rows = (await session.exec(select(Instance).where(
        Instance.status == "stopped", Instance.stopped_at < now - RETENTION))).all()
    done = 0
    for inst in rows:
        if not inst.volume_names:
            continue
        vols = list(inst.volume_names)
        for v in vols:
            try:
                await asyncio.to_thread(runtime.remove_volume, v)
            except Exception as e:  # noqa: BLE001
                if not _is_404(e):
                    raise
        inst.volume_names = []
        session.add(inst)
        if inst.owner_id:
            await post_notice(session, inst.owner_id, "scratch_reclaim", inst.id,
                              MESSAGE.format(name=inst.name))
        await audit(session, "scratch_reclaim", user_id=inst.owner_id, resource=inst.id,
                    detail={"volumes": vols})
        await session.commit()
        done += 1
    return done


async def scratch_reclaim_loop(session_factory, runtime) -> None:
    """Registered in main.py's leader_loops, so it only runs on the elected leader."""
    while True:
        try:
            async with session_factory() as s:
                n = await scratch_reclaim_tick(s, runtime, datetime.now(timezone.utc), True)
                if n:
                    log.info("reclaimed scratch volumes of %d instance(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("scratch reclaim failed")
        await asyncio.sleep(INTERVAL_S)
