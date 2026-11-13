"""Single off-switch for accounts (ADR-0022): kills sessions immediately."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import Instance, PosixUid, RefreshToken, User
from app.services.audit import audit
from app.services.k8s_homes import freeze_home
from app.services.session_audit import record_session_event

log = logging.getLogger(__name__)
LIVE = ("running", "idle")


def is_disabled(user: User) -> bool:
    """Single definition of "disabled": stamp set and account not re-enabled."""
    return user.disabled_at is not None and not user.is_active


async def _freeze_home(session: AsyncSession, user: User, runtime) -> None:
    """k8s only: label the home PVC frozen. Best effort; never blocks the disable."""
    if Settings().ROUTE_BACKEND != "k8s":
        return
    try:
        uid = (await session.exec(select(PosixUid.uid).where(
            PosixUid.user_key == user.id))).first()
        if uid is None:
            return
        if runtime is None:
            from app.services.k8s_runtime import instance_runtime
            runtime = instance_runtime()
        await asyncio.to_thread(freeze_home, runtime._c, uid,
                                Settings().K8S_INSTANCE_NAMESPACE)
    except Exception:
        log.exception("offboarding: home freeze failed for user %s", user.id)


async def disable_account(session: AsyncSession, user: User, reason: str,
                          actor: str | None, runtime=None) -> bool:
    """Disable ``user``; returns False (no-op) if already disabled.

    Bumping token_version rejects every issued access token at once; refresh
    tokens are revoked and live instances stopped in the same call.
    """
    if user.disabled_at is not None:
        return False
    now = datetime.now(timezone.utc)
    user.is_active = False
    user.disabled_at = now
    user.disabled_reason = reason
    user.token_version += 1
    session.add(user)
    await session.exec(update(RefreshToken).where(RefreshToken.user_id == user.id)
                       .values(revoked=True))
    insts = (await session.exec(select(Instance).where(
        Instance.owner_id == user.id, Instance.status.in_(LIVE)))).all()
    if insts and runtime is None:
        from app.services.k8s_runtime import instance_runtime
        runtime = instance_runtime()
    await _freeze_home(session, user, runtime)
    for inst in insts:
        if inst.container_id:
            try:
                await asyncio.to_thread(runtime.stop_container, inst.container_id)
            except Exception:  # keep going: the account must still end up disabled
                log.exception("offboarding: stop failed for instance %s", inst.id)
        inst.status = "stopped"
        inst.stopped_at = now
        session.add(inst)
        await record_session_event(session, inst, "stopped", action="session.stop",
                                   reason="offboarded")
    await audit(session, "account.disabled", user_id=actor, resource=user.id,
                detail={"reason": reason})
    await session.commit()
    return True
