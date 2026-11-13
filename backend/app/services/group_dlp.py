"""Effective per-user DLP policy from group overrides (ADR-0038)."""
from sqlmodel import select

from app.models import Group, UserGroup

DLP_DEFAULTS = {
    "clipboard_in": True, "clipboard_out": True, "upload": True,
    "download": False, "printing": False, "watermark": True,
}

# Names below are those in the pinned Selkies (selkies-defaults.ts). Selkies has no
# per-direction clipboard or env-configurable printing switch, so clipboard stays on
# only when both directions are allowed (fail closed) and printing is not configurable
# via env. STYX_WATERMARK_USER is read by the ADR-0058 pixelflux patch (05), which
# adds the UTC time itself (the watermark's time placeholder).
DLP_ENV_KEYS = frozenset({
    "SELKIES_CLIPBOARD_ENABLED", "SELKIES_FILE_TRANSFERS", "STYX_WATERMARK_USER",
})


def dlp_env(policy: dict[str, bool], username: str | None = None) -> dict[str, str]:
    """Selkies env enforcing the policy server-side.

    A watermark needs a non-empty identifier: the patch treats "" as unset.
    """
    env = {
        "SELKIES_CLIPBOARD_ENABLED": (
            "true" if policy["clipboard_in"] and policy["clipboard_out"] else "false"),
        "SELKIES_FILE_TRANSFERS": ",".join(
            d for d in ("upload", "download") if policy[d]) or "none",
    }
    if policy["watermark"]:
        if not username:
            raise ValueError("watermark requires a non-empty username")
        env["STYX_WATERMARK_USER"] = username
    return env


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
