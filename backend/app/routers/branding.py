from fastapi import APIRouter

from app.services.settings_store import settings

router = APIRouter()

_KEYS = ("brand_name", "brand_logo_url", "brand_accent")


@router.get("")
async def get_branding():
    """Public (pre-login) branding values; exposes only the three brand keys."""
    return {k: settings.get(k) for k in _KEYS}
