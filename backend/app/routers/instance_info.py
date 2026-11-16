"""Instance status/stats/keepalive/update/screenshot/events/logs routes."""
import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import Instance, ServiceTemplate, SessionEvent, User
from app.schemas import InstanceUpdate, SessionConfigUpdate, InstanceStatus
from app.security.deps import get_current_user, require_owner_or_admin
from app.services.docker_manager import DockerManager
from app.services.instance_deps import get_docker_manager, get_screenshot_service
from app.services.screenshot import ScreenshotService

router = APIRouter()

# Field allowlist for instance updates. Only these fields can be modified via PATCH.
_INSTANCE_UPDATE_FIELDS = {"name", "env_overrides", "session_config"}


@router.get("/{instance_id}/status", response_model=InstanceStatus)
async def get_instance_status(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    docker_status = {}
    if instance.container_id:
        docker_status = await asyncio.to_thread(docker.get_container_status, instance.container_id)

    now = datetime.now(timezone.utc)
    uptime = None
    if instance.started_at and instance.status == "running":
        started = instance.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        uptime = (now - started).total_seconds()

    idle = None
    if instance.last_activity and instance.status == "running":
        last_act = instance.last_activity
        if last_act.tzinfo is None:
            last_act = last_act.replace(tzinfo=timezone.utc)
        idle = (now - last_act).total_seconds()

    from app.services import pull_progress
    pp = pull_progress.get(instance_id)

    return InstanceStatus(
        id=instance.id,
        status=docker_status.get("status", instance.status),
        container_id=instance.container_id,
        uptime_seconds=uptime,
        idle_seconds=idle,
        session_config=instance.session_config,
        pull_percent=pp["percent"] if pp else None,
        pull_detail=pp["detail"] if pp else None,
    )


@router.get("/{instance_id}/stats")
async def get_instance_stats(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if not instance.container_id or instance.status not in ("running", "idle"):
        return {"cpu_percent": 0, "memory_mb": 0, "memory_limit_mb": 0, "memory_percent": 0}

    return await asyncio.to_thread(docker.instance_usage, instance.container_id)


@router.post("/{instance_id}/keepalive", response_model=Instance)
async def keepalive(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    instance.last_activity = datetime.now(timezone.utc)
    if instance.status == "idle":
        instance.status = "running"
    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return instance


@router.patch("/{instance_id}", response_model=Instance)
async def update_instance(
    instance_id: str,
    body: InstanceUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    # Apply only allowlisted fields
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in _INSTANCE_UPDATE_FIELDS:
            setattr(instance, field, value)

    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return instance


@router.patch("/{instance_id}/session", response_model=Instance)
async def update_session_config(
    instance_id: str,
    body: SessionConfigUpdate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    config = instance.session_config or {}
    for field, value in body.model_dump(exclude_unset=True).items():
        config[field] = value
    instance.session_config = config

    session.add(instance)
    await session.commit()
    await session.refresh(instance)
    return instance


@router.get("/{instance_id}/screenshot")
async def get_screenshot(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    screenshots: ScreenshotService = Depends(get_screenshot_service),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    path = screenshots.get_path(instance_id)
    if not path:
        raise HTTPException(404, "No screenshot available")

    from app.routers.instance_thumbs import head as _head, sniff_image_type
    media = sniff_image_type(_head(path)) or "image/png"
    return FileResponse(path, media_type=media)


@router.post("/{instance_id}/screenshot/refresh")
async def refresh_screenshot(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    screenshots: ScreenshotService = Depends(get_screenshot_service),
    user: User = Depends(get_current_user),
):
    """Capture a fresh screenshot on demand (via the Selkies #shared view-only
    mirror — never steals the session). Returns {"ok": bool}."""
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if Settings().ROUTE_BACKEND == "k8s":
        return {"ok": False, "reason": "screenshots are not available on Kubernetes"}
    if instance.status not in ("running", "idle") or not instance.container_id:
        return {"ok": False, "reason": "not running"}

    tmpl = await session.get(ServiceTemplate, instance.template_id)
    port = tmpl.internal_port if tmpl else 3001
    protocol = tmpl.internal_protocol if tmpl else "https"
    try:
        ok = await screenshots.capture(instance.id, instance.container_id, port, protocol)
    finally:
        await screenshots.close()
    return {"ok": ok}


@router.get("/{instance_id}/events")
async def get_instance_events(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    from sqlmodel import desc
    result = await session.exec(
        select(SessionEvent)
        .where(SessionEvent.instance_id == instance_id)
        .order_by(desc(SessionEvent.id))
        .limit(20)
    )
    events = result.all()
    return [
        {
            "type": ev.event_type,
            "time": "recent",
            "details": ev.details.get("error", "")[:200] if ev.details else None,
        }
        for ev in events
    ]


@router.get("/{instance_id}/logs")
async def get_instance_logs(
    instance_id: str,
    lines: int = Query(default=500, le=2000),
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if not instance.container_id:
        return []

    try:
        return await asyncio.to_thread(docker.instance_logs, instance.container_id, lines)
    except Exception:
        return []
