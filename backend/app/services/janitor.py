"""Leader-only janitor: batched purge of expired denylist, ban and abuse rows."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import DateTime, bindparam, delete, inspect, text
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import BannedIP, RevokedAccessToken

log = logging.getLogger("styx.janitor")
_settings = Settings()
INTERVAL_S = 60
BATCH = 1000
# Abuse tables (alembic 0002): table -> expiry column. Skipped if absent.
# auth_fail_events.at is an event time: purged only once older than fail_window().
_ABUSE_TABLES = {"auth_fail_events": "at", "auth_blocks": "until",
                 "rate_counters": "expires_at"}
_TS = DateTime(timezone=True)  # TIMESTAMPTZ on Postgres; tz-dropping text on SQLite
_MODELS = ((RevokedAccessToken, RevokedAccessToken.jti, RevokedAccessToken.expires_at),
           (BannedIP, BannedIP.ip, BannedIP.expires_at))


def fail_window() -> int:
    """Seconds a fail event can still count toward any lockout or ban window."""
    return max(_settings.LOCKOUT_DURATION, _settings.BAN_FAIL_WINDOW, _settings.BAN_DURATION)


async def purge_expired(session: AsyncSession, batch: int = BATCH,
                        now: datetime | None = None) -> int:
    """Delete expired rows in batches; returns rows deleted."""
    aware = now or datetime.now(timezone.utc)
    if aware.tzinfo is None:
        aware = aware.replace(tzinfo=timezone.utc)
    now = aware.astimezone(timezone.utc).replace(tzinfo=None)  # models use naive UTC
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
    row = "ctid" if session.get_bind().dialect.name == "postgresql" else "rowid"
    for table, col in _ABUSE_TABLES.items():
        if table not in existing:
            continue
        cutoff = aware - timedelta(seconds=fail_window()) if col == "at" else aware
        # table/col names are constants above, never user input
        stmt = text(f"DELETE FROM {table} WHERE {row} IN (SELECT {row} FROM {table} "
                    f"WHERE {col} < :cutoff LIMIT :n)").bindparams(bindparam("cutoff", type_=_TS))
        while True:
            res = await session.exec(stmt, params={"cutoff": cutoff, "n": batch})
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
