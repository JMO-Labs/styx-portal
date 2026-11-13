"""Effective per-user DLP policy from group overrides (ADR-0038)."""
from sqlmodel import select

from app.models import Group, UserGroup

DLP_DEFAULTS = {
    "clipboard_in": True, "clipboard_out": True, "upload": True,
    "download": False, "printing": False, "watermark": True,
}

# Env names verified against the pinned selkies==2.2.0 (scripts/build_agent_artifacts.sh):
# upstream tag 2.2.0 (9e0d8e7c), src/selkies/settings.py settings enable_clipboard
# (true/in/out/false), file_transfers and printing_enabled (default true, so it is
# always set), read as SELKIES_<NAME>. STYX_WATERMARK_USER is read by our pixelflux
# watermark patch (patches/selkies/05-pixelflux-watermark.patch, enterprise 89596bb),
# which adds the UTC time itself. SELKIES_CLIPBOARD_ENABLED is not a Selkies env (only
# a derived client setting); it is listed so a template value is stripped.
DLP_ENV_KEYS = frozenset({
    "SELKIES_ENABLE_CLIPBOARD", "SELKIES_FILE_TRANSFERS", "SELKIES_PRINTING_ENABLED",
    "STYX_WATERMARK_USER", "SELKIES_CLIPBOARD_ENABLED",
})
_CLIPBOARD = {(True, True): "true", (True, False): "in", (False, True): "out",
              (False, False): "false"}


def dlp_env(policy: dict[str, bool], username: str | None = None) -> dict[str, str]:
    """Selkies env enforcing the policy server-side.

    A watermark needs a non-empty identifier: the patch treats "" as unset.
    """
    env = {
        "SELKIES_ENABLE_CLIPBOARD": _CLIPBOARD[
            (bool(policy["clipboard_in"]), bool(policy["clipboard_out"]))],
        "SELKIES_FILE_TRANSFERS": ",".join(
            d for d in ("upload", "download") if policy[d]) or "none",
        "SELKIES_PRINTING_ENABLED": "true" if policy["printing"] else "false",
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
