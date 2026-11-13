"""Leader-only session reaper (ADR-0039, AC-12).

Each pass reads every running instance's gateway ``GET /styx/state``:
- a change in ``locked`` -> SessionEvent + ECS ``session.lock``/``session.unlock``;
- no connections and disconnected longer than SESSION_DISCONNECT_MAX_H -> stop;
- SESSION_WARN_MIN before SESSION_MAX_H -> instance.notice; at SESSION_MAX_H -> stop.
An unreachable gateway changes nothing (fail open),.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import select

from app.config import Settings
from app.models import Instance, SessionEvent
from app.services.audit_ecs import emit, session_event

log = logging.getLogger("styx.session_reaper")


def _naive_utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


async def _was_locked(session, inst_id: str) -> bool:
    last = (await session.exec(
        select(SessionEvent.event_type)
        .where(SessionEvent.instance_id == inst_id,
               SessionEvent.event_type.in_(["locked", "unlocked"]))
        .order_by(SessionEvent.id.desc()).limit(1))).first()
    return last == "locked"


async def _has_event(session, inst_id: str, kind: str) -> bool:
    return (await session.exec(select(SessionEvent.id).where(
        SessionEvent.instance_id == inst_id, SessionEvent.event_type == kind))).first() is not None


async def reaper_pass(session, stop, fetch_state, *, cfg: Settings | None = None,
                      now: datetime | None = None, is_leader=lambda: True, audit=emit) -> int:
    """One pass; returns the number of instances stopped. `stop`/`fetch_state` are sync."""
    if not is_leader():
        return 0
    cfg = cfg or Settings()
    now = _naive_utc(now)
    rows = (await session.exec(
        select(Instance).where(Instance.status.in_(["running", "idle"])))).all()
    stopped = 0
    for inst in rows:
        try:
            state = await asyncio.to_thread(fetch_state, inst)
        except Exception as e:  # noqa: BLE001
            log.warning("gateway state unreachable for %s (%s)", inst.id, e.__class__.__name__)
            continue
        if not isinstance(state, dict):
            continue
        if "locked" in state and bool(state["locked"]) != await _was_locked(session, inst.id):
            kind = "locked" if state["locked"] else "unlocked"
            session.add(SessionEvent(instance_id=inst.id, event_type=kind))
            audit(session_event("session.lock" if state["locked"] else "session.unlock",
                                session_id=inst.id, kind="instance", user_id=inst.owner_id))
        reason = None
        ts = state.get("last_disconnect_ts")
        if (state.get("active_connections") == 0 and ts is not None
                and datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
                <= now - timedelta(hours=cfg.SESSION_DISCONNECT_MAX_H)):
            reason = "disconnected"
        if inst.started_at:
            end = inst.started_at + timedelta(hours=cfg.SESSION_MAX_H)
            if end <= now:
                reason = "max_duration"
            elif end - timedelta(minutes=cfg.SESSION_WARN_MIN) <= now and reason is None \
                    and not await _has_event(session, inst.id, "max_duration_warned"):
                inst.notice = (f"This session reaches its {cfg.SESSION_MAX_H:g} h limit at "
                               f"{end:%H:%M} UTC and will be stopped: save your work.")
                session.add(inst)
                session.add(SessionEvent(instance_id=inst.id, event_type="max_duration_warned"))
        if reason:
            await asyncio.to_thread(stop, inst)
            inst.status = "stopped"
            inst.stopped_at = now
            session.add(inst)
            session.add(SessionEvent(instance_id=inst.id, event_type="reaped",
                                     details={"reason": reason}))
            audit(session_event("session.stop", session_id=inst.id, kind="instance",
                                user_id=inst.owner_id, reason=reason))
            stopped += 1
    await session.commit()
    return stopped


async def session_reaper_loop() -> None:
    from app.database import async_session
    from app.services.k8s_runtime import instance_runtime
    from app.services.leader import get_elector
    from app.services.route_writer import refresh_routes_from_db
    cfg = Settings()
    runtime = instance_runtime()
    elector = get_elector()

    def stop(inst: Instance) -> None:
        if inst.container_id:
            runtime.stop_container(inst.container_id)

    with httpx.Client(timeout=5.0) as client:
        def fetch(inst: Instance) -> dict:
            url = (f"http://{inst.container_id}.{cfg.K8S_INSTANCE_NAMESPACE}.svc:"
                   f"{cfg.GATEWAY_PORT}/styx/state")
            r = client.get(url)
            r.raise_for_status()
            return r.json()

        while True:
            await asyncio.sleep(cfg.SESSION_REAPER_INTERVAL_S)
            try:
                async with async_session() as session:
                    n = await reaper_pass(session, stop, fetch, cfg=cfg,
                                          is_leader=lambda: elector.is_leader)
                    if n:
                        await refresh_routes_from_db(session)
            except Exception:  # noqa: BLE001
                log.warning("session reaper tick failed", exc_info=True)
