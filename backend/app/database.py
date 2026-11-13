import json
import os
import stat
from pathlib import Path

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.db_migrate import BACKUP_SUFFIX, migrate
from app.models import ServicePreset, ServiceTemplate

settings = Settings()
# TODO(#24): behind the CNPG pooler (transaction mode) pass
# connect_args={"statement_cache_size": 0, "prepared_statement_cache_size": 0}.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def _restrict_db_perms(url=None):
    """Restrict the SQLite file and its pre-Alembic backup to 0600. No-op for Postgres."""
    url = url or engine.url
    if url.get_backend_name() != "sqlite" or url.database in (None, "", ":memory:"):
        return
    for path in (Path(url.database), Path(f"{url.database}{BACKUP_SUFFIX}")):
        if path.exists():
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600


async def init_db():
    await migrate(engine)
    _restrict_db_perms()
    async with async_session() as session:
        await seed_templates(session, settings.TEMPLATES_DIR)
        await seed_service_presets(session, settings.SERVICE_PRESETS_DIR)
        from app.services.enterprise_services import seed_enterprise_services
        await seed_enterprise_services(session)


async def get_session():
    async with async_session() as session:
        yield session


async def seed_templates(session: AsyncSession, templates_dir: str):
    if not os.path.isdir(templates_dir):
        return
    for filename in os.listdir(templates_dir):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(templates_dir, filename)
        with open(filepath) as f:
            data = json.load(f)

        result = await session.exec(
            select(ServiceTemplate).where(ServiceTemplate.name == data["name"])
        )
        existing = result.first()
        if existing:
            continue

        template = ServiceTemplate(**data)
        session.add(template)

    await session.commit()


async def seed_service_presets(session: AsyncSession, presets_dir: str):
    """Upsert of templates/services/*.json into service_presets (built-in, read-only)."""
    if not os.path.isdir(presets_dir):
        return
    for filename in sorted(os.listdir(presets_dir)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(presets_dir, filename)) as f:
            data = json.load(f)
        existing = await session.get(ServicePreset, data["id"])
        if existing is None:
            session.add(ServicePreset(**data))
            continue
        # Rebuild every field: a key the file dropped must not survive from an older seed.
        for k, v in ServicePreset(**data).model_dump().items():
            setattr(existing, k, v)
        session.add(existing)
    await session.commit()
