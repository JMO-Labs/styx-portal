"""Service thumbnails in the DB (bytea/BLOB) so every replica serves what any replica captured."""
from datetime import datetime, timezone

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
    row = await session.get(ServiceThumbnail, service_id)
    if row is None:
        session.add(ServiceThumbnail(service_id=service_id, data=data, updated_at=now))
    else:
        row.data, row.updated_at = data, now
        session.add(row)
    await session.commit()


async def get(session: AsyncSession, service_id: str) -> bytes | None:
    row = await session.get(ServiceThumbnail, service_id)
    return row.data if row else None


async def delete(session: AsyncSession, service_id: str) -> None:
    row = await session.get(ServiceThumbnail, service_id)
    if row is not None:
        await session.delete(row)
