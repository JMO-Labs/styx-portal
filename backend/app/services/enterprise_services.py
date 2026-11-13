"""Seed Wiki.js / Element as proxied-service rows on the enterprise profile."""
import logging

from sqlalchemy.exc import IntegrityError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import settings
from app.models import ProxiedService

log = logging.getLogger(__name__)

# (slug, display name, icon, settings attribute); preset_id == slug.
_SERVICES = (
    ("wikijs", "Wiki.js", "📚", "WIKI_URL"),
    ("element", "Element", "💬", "ELEMENT_URL"),
)


async def seed_enterprise_services(session: AsyncSession) -> None:
    """Create a row per configured URL once; never touch an existing slug.

    Empty allowed_groups = visible to every user. Safe across replicas: a
    concurrent insert loses on the unique slug and is ignored.
    """
    for slug, name, icon, attr in _SERVICES:
        url = (getattr(settings, attr, "") or "").strip()
        if not url:
            continue
        existing = (await session.exec(
            select(ProxiedService).where(ProxiedService.slug == slug))).first()
        if existing:
            continue
        session.add(ProxiedService(
            slug=slug, name=name, icon=icon, kind="url", upstream_url=url,
            mount_mode="path", auth_mode="app-native", preset_id=slug,
        ))
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            log.info("enterprise service %s already created by another replica", slug)
