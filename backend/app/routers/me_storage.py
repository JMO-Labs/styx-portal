from fastapi import APIRouter, Depends
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import User
from app.security.deps import get_current_user
from app.services.home_usage import home_usage
from app.services.posix_uid import allocate_uid

router = APIRouter()
WARN_PERCENT = 80


async def user_storage(session: AsyncSession, user_id: str) -> dict:
    empty = {"used_bytes": None, "quota_bytes": None, "percent": None, "warn": False}
    url = Settings().PROMETHEUS_URL
    if not url:
        return empty
    usage = await home_usage(await allocate_uid(session, user_id), url)
    if usage is None:
        return empty
    return {**usage, "warn": usage["percent"] >= WARN_PERCENT}


@router.get("/storage")
async def get_storage(user: User = Depends(get_current_user),
                      session: AsyncSession = Depends(get_session)):
    return await user_storage(session, user.id)
