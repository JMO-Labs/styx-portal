"""Leader-only critical-CVE recycle (ADR-0030).

Each pass asks Harbor for the vulnerability report of every running instance's
pinned digest. First CRITICAL: warn the user (instance.notice) and set
recycle_deadline = now + grace (24 h). Later passes stop instances past it.
Harbor errors change nothing (fail open: never stop sessions on a blind spot).
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx
from sqlmodel import select

from app.config import Settings
from app.models import Instance, ServiceTemplate, SessionEvent
from app.services.image_digest import _split

log = logging.getLogger("styx.cve_recycle")


def _naive_utc(now: datetime | None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now


def has_critical(image: str, digest: str, cfg: Settings, client: httpx.Client) -> bool | None:
    """True/False from Harbor's report; None if unknown (not on Harbor, or error)."""
    split = _split(image, urlsplit(cfg.HARBOR_URL).netloc.lower())
    if not split:
        return None
    _, project, repo = split
    url = (f"{cfg.HARBOR_URL.rstrip('/')}/api/v2.0/projects/{project}/repositories/"
           f"{quote(quote(repo, safe=''), safe='')}/artifacts/{digest}/additions/vulnerabilities")
    auth = (cfg.HARBOR_USER, cfg.HARBOR_PASSWORD) if cfg.HARBOR_USER else None
    try:
        r = client.get(url, auth=auth)
        r.raise_for_status()
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("harbor vulnerability lookup failed for %s (%s)", digest, e.__class__.__name__)
        return None
    if not isinstance(data, dict):
        return None
    return any(isinstance(v, dict) and str(v.get("severity", "")).upper() == "CRITICAL"
               for rep in data.values() if isinstance(rep, dict)
               for v in rep.get("vulnerabilities") or [])


def _warning(deadline: datetime) -> str:
    return ("A critical security vulnerability was found in this desktop image. "
            f"The session will be stopped by {deadline:%Y-%m-%d %H:%M} UTC (within 24 h): "
            "save your work and relaunch to get the patched image.")


async def recycle_pass(session, stop, cfg: Settings, client: httpx.Client, *,
                       now: datetime | None = None, is_leader=lambda: True) -> int:
    """One pass; returns the number of instances stopped. `stop(instance)` is sync."""
    if not is_leader() or not cfg.HARBOR_URL:
        return 0
    now = _naive_utc(now)
    rows = (await session.exec(
        select(Instance, ServiceTemplate.image)
        .join(ServiceTemplate, ServiceTemplate.id == Instance.template_id)
        .where(Instance.status.in_(["running", "idle"]), Instance.image_digest.is_not(None))
    )).all()
    stopped = 0
    for inst, image in rows:
        if inst.recycle_deadline is not None:
            if inst.recycle_deadline <= now:
                await asyncio.to_thread(stop, inst)
                inst.status = "stopped"
                inst.stopped_at = now
                session.add(inst)
                session.add(SessionEvent(instance_id=inst.id, event_type="cve_recycled",
                                         details={"digest": inst.image_digest}))
                stopped += 1
            continue
        crit = await asyncio.to_thread(has_critical, image, inst.image_digest, cfg, client)
        if crit:
            inst.recycle_deadline = now + timedelta(hours=cfg.CVE_RECYCLE_GRACE_H)
            inst.notice = _warning(inst.recycle_deadline)
            session.add(inst)
            session.add(SessionEvent(instance_id=inst.id, event_type="cve_warned",
                                     details={"digest": inst.image_digest}))
    await session.commit()
    return stopped


async def cve_recycle_loop() -> None:
    from app.database import async_session
    from app.services.k8s_runtime import instance_runtime
    from app.services.leader import get_elector
    from app.services.route_writer import refresh_routes_from_db
    cfg = Settings()
    docker = instance_runtime()
    elector = get_elector()

    def stop(inst: Instance) -> None:
        if inst.container_id:
            docker.stop_container(inst.container_id)

    with httpx.Client(timeout=5.0) as client:
        while True:
            await asyncio.sleep(cfg.CVE_RECYCLE_INTERVAL_S)
            try:
                async with async_session() as session:
                    n = await recycle_pass(session, stop, cfg, client,
                                           is_leader=lambda: elector.is_leader)
                    if n:
                        await refresh_routes_from_db(session)
            except Exception:  # noqa: BLE001
                log.warning("cve recycle tick failed", exc_info=True)
