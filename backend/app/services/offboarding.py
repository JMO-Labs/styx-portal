"""Single off-switch for accounts (ADR-0022): kills sessions immediately."""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Instance, RefreshToken, SessionEvent, User
from app.services.audit import audit

log = logging.getLogger(__name__)
LIVE = ("running", "idle")


def is_disabled(user: User) -> bool:
    """Single definition of "disabled": stamp set and account not re-enabled."""
    return user.disabled_at is not None and not user.is_active


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
    for inst in insts:
        if inst.container_id:
            try:
                await asyncio.to_thread(runtime.stop_container, inst.container_id)
            except Exception:  # keep going: the account must still end up disabled
                log.exception("offboarding: stop failed for instance %s", inst.id)
        inst.status = "stopped"
        inst.stopped_at = now
        session.add(inst)
        session.add(SessionEvent(instance_id=inst.id, event_type="stopped"))
    await audit(session, "account.disabled", user_id=actor, resource=user.id,
                detail={"reason": reason})
    await session.commit()
    return True
