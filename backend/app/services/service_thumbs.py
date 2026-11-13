"""Service thumbnails in the DB (bytea/BLOB) so every replica serves what any replica captured."""
from datetime import datetime, timezone

from sqlalchemy import delete as sa_delete
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import ServiceThumbnail


class ThumbnailTooLarge(ValueError):
    pass


def max_bytes() -> int:
    return Settings().SERVICE_THUMBNAIL_MAX_BYTES


async def put(session: AsyncSession, service_id: str, data: bytes) -> None:
    if len(data) > max_bytes():
        raise ThumbnailTooLarge(f"{len(data)} > {max_bytes()} bytes")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        row = await session.get(ServiceThumbnail, service_id)
        if row is None:
            session.add(ServiceThumbnail(service_id=service_id, data=data, updated_at=now))
        else:
            row.data, row.updated_at = data, now
            session.add(row)
        await session.commit()
    except Exception:
        # Leave the session usable for the next service in the same pass.
        await session.rollback()
        raise


async def get(session: AsyncSession, service_id: str) -> bytes | None:
    row = await session.get(ServiceThumbnail, service_id)
    return row.data if row else None


async def delete(session: AsyncSession, service_id: str) -> None:
    # Bulk DELETE (not ORM): avoids a stale-row warning when the FK cascade wins the race on PG.
    await session.exec(sa_delete(ServiceThumbnail).where(col(ServiceThumbnail.service_id) == service_id))
