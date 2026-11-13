"""Per-group CPU-tier overrides (ADR-0031) resolved for a launching user."""
import re

from fastapi import HTTPException
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Group, User, UserGroup
from app.services.group_dlp import DLP_ENV_KEYS, dlp_env, user_group_dlp
from app.services.session_policy import DEFAULT_IDLE_LOCK_S, effective_idle_lock_s

_MULT = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def _mem_bytes(v: str) -> float:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)([KkMmGgTt])[iIbB]?", v.strip())
    return float(m[1]) * _MULT[m[2].lower()] if m else 0.0


def _pixels(res: str) -> int:
    w, _, h = res.partition("x")
    return int(w) * int(h)


def resolve_group_tier(groups: list[Group]) -> dict:
    """Merge group overrides into one dict (keys: cpu, memory, fps, resolution, hidpi).

    A user in several groups gets the most generous value per field: highest
    cpu, memory and fps; resolution with the most pixels; hidpi if any group
    enables it. Fields no group sets are omitted (global CPU-tier default applies).
    """
    def best(attr, key):
        vals = [getattr(g, attr) for g in groups if getattr(g, attr) is not None]
        return max(vals, key=key) if vals else None

    picked = {
        "cpu": best("tier_cpu", float),
        "memory": best("tier_memory", _mem_bytes),
        "fps": best("tier_fps", int),
        "resolution": best("tier_resolution", _pixels),
        "hidpi": best("tier_hidpi", bool),
    }
    return {k: v for k, v in picked.items() if v is not None}


async def user_group_tier(session: AsyncSession, user_id: str | None) -> dict:
    if not user_id:
        return {}
    groups = (await session.exec(
        select(Group).join(UserGroup, col(UserGroup.group_id) == Group.id)
        .where(UserGroup.user_id == user_id))).all()
    return resolve_group_tier(list(groups))


def tier_env(tier: dict) -> dict[str, str]:
    """Selkies env for the group's resolution/fps/HiDPI overrides."""
    env: dict[str, str] = {}
    if "resolution" in tier:
        w, _, h = tier["resolution"].partition("x")
        env |= {"SELKIES_MANUAL_WIDTH": w, "SELKIES_MANUAL_HEIGHT": h}
    if "fps" in tier:
        env["SELKIES_FRAMERATE"] = str(tier["fps"])
    if "hidpi" in tier:
        env["SELKIES_SCALING_DPI"] = "192" if tier["hidpi"] else "96"
    return env


# Idle-lock policy keys: set by the portal, never by templates or owners.
POLICY_ENV_KEYS = frozenset({"STYX_LOCK_IDLE_S", "STYX_INSTANCE_ID", "STYX_UNLOCK_URL"})


def merge_launch_env(defaults: dict, template_env: dict | None, overrides: dict | None) -> dict:
    """Group defaults < template env < owner overrides. Policy keys, and DLP keys
    when DLP is enforced (present in ``defaults``), come from ``defaults`` only:
    a template or owner cannot re-enable a channel or defeat the idle lock."""
    locked = POLICY_ENV_KEYS | (DLP_ENV_KEYS if DLP_ENV_KEYS & defaults.keys() else frozenset())

    def clean(d):
        return {k: v for k, v in (d or {}).items() if k not in locked}
    return {**defaults, **clean(template_env), **clean(overrides),
            **{k: v for k, v in defaults.items() if k in locked}}


async def launch_overrides(session: AsyncSession, runtime, instance, template):
    """(env, memory_limit, cpu_limit) for a launch. env merges group defaults,
    template env and the instance's env_overrides (policy and DLP keys
    authoritative). Template limits win over group overrides, which win over the
    global CPU-tier defaults. Kubernetes only (the CPU tier is not applied on the
    Docker path)."""
    from app.services.k8s_instances import K8sInstanceRuntime

    tpl_env = getattr(template, "env_vars", None)
    user_env = getattr(instance, "env_overrides", None)
    if not isinstance(runtime, K8sInstanceRuntime):
        return merge_launch_env({}, tpl_env, user_env), template.memory_limit, template.cpu_limit
    if not instance.owner_id:
        # DLP watermark needs an owner identity: refuse rather than launch unmarked.
        raise HTTPException(409, "Instance has no owner; DLP policy cannot be applied")
    tier = await user_group_tier(session, instance.owner_id)
    owner = await session.get(User, instance.owner_id)
    lock_s = await effective_idle_lock_s(owner, session) if owner else DEFAULT_IDLE_LOCK_S
    dlp = dlp_env(await user_group_dlp(session, instance.owner_id),
                  (owner.username if owner else None) or instance.owner_id)
    defaults = {**tier_env(tier), **dlp, "STYX_INSTANCE_ID": instance.id,
                "STYX_LOCK_IDLE_S": str(lock_s)}
    return (merge_launch_env(defaults, tpl_env, user_env),
            template.memory_limit or tier.get("memory"), template.cpu_limit or tier.get("cpu"))
