"""Cross-replica settings freshness (Postgres only).

Each replica re-reads system_settings every SETTINGS_SYNC_S seconds, so a write
on one replica is visible on the others within one interval. SQLite is
single-process: nothing to sync, the loop exits immediately.
"""
import asyncio
import logging

from app.services.settings_store import SettingsService

logger = logging.getLogger("styx-portal")
DEFAULT_INTERVAL_S = 2.0   # well under the 5 s requirement; one tiny SELECT per tick


async def sync_once(session, svc: SettingsService) -> bool:
    if session.get_bind().dialect.name != "postgresql":
        return False
    await svc.reload(session)
    await session.rollback()   # end the read txn so the next tick sees new commits
    return True


async def settings_sync_loop(factory, svc: SettingsService, interval: float = DEFAULT_INTERVAL_S):
    while True:
        try:
            async with factory() as session:
                if not await sync_once(session, svc):
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - keep last-known values on a DB blip
            logger.warning("settings sync failed", exc_info=True)
        await asyncio.sleep(interval)
