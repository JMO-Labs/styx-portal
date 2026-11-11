"""Leader-only janitor: batched purge of expired denylist, ban and abuse rows."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import delete, inspect, text
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import BannedIP, RevokedAccessToken

log = logging.getLogger("styx.janitor")
INTERVAL_S = 60
BATCH = 1000
# New abuse tables (store, Child 4): table -> expiry column. Skipped if absent.
_ABUSE_TABLES = {"auth_fail_events": "at", "auth_blocks": "expires_at",
                 "rate_counters": "expires_at"}
_MODELS = ((RevokedAccessToken, RevokedAccessToken.jti, RevokedAccessToken.expires_at),
           (BannedIP, BannedIP.ip, BannedIP.expires_at))


async def purge_expired(session: AsyncSession, batch: int = BATCH,
                        now: datetime | None = None) -> int:
    """Delete expired rows in batches; returns rows deleted."""
    from sqlmodel import select
    now = (now or datetime.now(timezone.utc)).replace(tzinfo=None)
    total = 0
    for model, pk, exp in _MODELS:
        while True:
            ids = (await session.exec(select(pk).where(exp < now).limit(batch))).all()
            if not ids:
                break
            await session.exec(delete(model).where(pk.in_(ids)))
            await session.commit()
            total += len(ids)
    existing = set(await session.run_sync(lambda s: inspect(s.connection()).get_table_names()))
    for table, col in _ABUSE_TABLES.items():
        if table not in existing:
            continue
        while True:  # table/col names are constants above, never user input
            res = await session.exec(text(
                f"DELETE FROM {table} WHERE ctid IN (SELECT ctid FROM {table} "
                f"WHERE {col} < :now LIMIT :n)" if session.get_bind().dialect.name == "postgresql"
                else f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} "
                     f"WHERE {col} < :now LIMIT :n)"), {"now": now, "n": batch})
            await session.commit()
            total += res.rowcount
            if res.rowcount < batch:
                break
    return total


async def janitor_loop() -> None:
    from app.database import async_session
    while True:
        await asyncio.sleep(INTERVAL_S)
        try:
            async with async_session() as session:
                n = await purge_expired(session)
            if n:
                log.info("janitor purged %d expired rows", n)
        except Exception:  # noqa: BLE001
            log.warning("janitor tick failed", exc_info=True)
