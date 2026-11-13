"""Effective per-user DLP policy from group overrides (ADR-0038)."""
from sqlmodel import select

from app.models import Group, UserGroup

DLP_DEFAULTS = {
    "clipboard_in": True, "clipboard_out": True, "upload": True,
    "download": False, "printing": False, "watermark": True,
}

# SELKIES_CLIPBOARD_ENABLED is the name pinned in selkies-defaults.ts; the
# SELKIES_ENABLE_CLIPBOARD alias carries the in/out direction. STYX_WATERMARK_USER
# is read by the ADR-0058 pixelflux patch (05), which adds the UTC time itself.
DLP_ENV_KEYS = frozenset({
    "SELKIES_CLIPBOARD_ENABLED", "SELKIES_ENABLE_CLIPBOARD", "SELKIES_FILE_TRANSFERS",
    "SELKIES_PRINTING_ENABLED", "STYX_WATERMARK_USER",
})


def dlp_env(policy: dict[str, bool], username: str | None = None) -> dict[str, str]:
    """Selkies env enforcing the policy server-side. Printing on sets no key."""
    cin, cout = policy["clipboard_in"], policy["clipboard_out"]
    env = {
        "SELKIES_CLIPBOARD_ENABLED": "true" if cin or cout else "false",
        "SELKIES_ENABLE_CLIPBOARD": (
            "true" if cin and cout else "in" if cin else "out" if cout else "false"),
        "SELKIES_FILE_TRANSFERS": ",".join(
            d for d in ("upload", "download") if policy[d]) or "none",
    }
    if not policy["printing"]:
        env["SELKIES_PRINTING_ENABLED"] = "false"
    if policy["watermark"]:
        env["STYX_WATERMARK_USER"] = username or ""
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
