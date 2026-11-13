"""Effective per-user DLP policy from group overrides (ADR-0038)."""
from sqlmodel import select

from app.models import Group, UserGroup

DLP_DEFAULTS = {
    "clipboard_in": True, "clipboard_out": True, "upload": True,
    "download": False, "printing": False, "watermark": True,
}


def resolve_group_dlp(groups) -> dict[str, bool]:
    """Most restrictive value wins across groups with a non-empty approval ref.

    Allow-type fields: allowed only if every overriding group allows.
    Watermark: on if any overriding group wants it. A None field is no override.
    """
    approved = [g for g in groups if g.dlp_approval_ref]
    result = dict(DLP_DEFAULTS)
    for key in DLP_DEFAULTS:
        vals = [v for g in approved if (v := getattr(g, f"dlp_{key}")) is not None]
        if vals:
            result[key] = any(vals) if key == "watermark" else all(vals)
    return result


async def user_group_dlp(session, user_id: str) -> dict[str, bool]:
    r = await session.exec(
        select(Group).join(UserGroup, UserGroup.group_id == Group.id)
        .where(UserGroup.user_id == user_id))
    return resolve_group_dlp(list(r.all()))
