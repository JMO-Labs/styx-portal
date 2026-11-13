"""Per-group CPU-tier overrides (ADR-0031) resolved for a launching user."""
import re

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Group, User, UserGroup
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
        select(Group).join(UserGroup, UserGroup.group_id == Group.id)
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


async def launch_overrides(session: AsyncSession, runtime, instance, template):
    """(env defaults, memory_limit, cpu_limit) for a launch. Template values win over
    group overrides, which win over the global CPU-tier defaults. Kubernetes only
    (the CPU tier is not applied on the Docker path)."""
    from app.services.k8s_instances import K8sInstanceRuntime

    if not isinstance(runtime, K8sInstanceRuntime):
        return {}, template.memory_limit, template.cpu_limit
    tier = await user_group_tier(session, instance.owner_id)
    owner = await session.get(User, instance.owner_id) if instance.owner_id else None
    lock_s = await effective_idle_lock_s(owner, session) if owner else DEFAULT_IDLE_LOCK_S
    return ({**tier_env(tier), "STYX_INSTANCE_ID": instance.id,
             "STYX_LOCK_IDLE_S": str(lock_s)}, template.memory_limit or tier.get("memory"),
            template.cpu_limit or tier.get("cpu"))
