"""Instance pause/unpause/delete routes (included into the instances router)."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.database import get_session
from app.models import Instance, ServiceTemplate, PulledImage, User
from app.security.deps import get_current_user, require_owner_or_admin
from app.services import profiles, slo_metrics
from app.services.audit import audit
from app.services.docker_manager import DockerManager
from app.services.instance_build import _refresh_routes
from app.services.instance_deps import get_docker_manager
from app.services.session_audit import record_session_event

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/{instance_id}/pause", response_model=Instance)
async def pause_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if instance.status != "running" and instance.status != "idle":
        raise HTTPException(409, "Instance not running")

    await asyncio.to_thread(docker.pause_container, cast(str, instance.container_id))
    instance.status = "paused"
    session.add(instance)

    await record_session_event(session, instance, "paused", action="session.lock")
    await session.commit()
    await session.refresh(instance)
    await _refresh_routes(session)
    return instance


@router.post("/{instance_id}/unpause", response_model=Instance)
async def unpause_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    t0 = time.monotonic()
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if instance.status != "paused":
        raise HTTPException(409, "Instance not paused")

    await asyncio.to_thread(docker.unpause_container, cast(str, instance.container_id))
    instance.status = "running"
    instance.last_activity = datetime.now(timezone.utc)
    session.add(instance)

    await record_session_event(session, instance, "unpaused", action="session.unlock")
    await session.commit()
    slo_metrics.observe_since("resume", "ok", t0)
    await session.refresh(instance)
    await _refresh_routes(session)
    return instance


@router.delete("/{instance_id}", status_code=204)
async def delete_instance(
    instance_id: str,
    remove_volumes: bool = Query(False),
    remove_image: bool = Query(False),
    remove_template: bool = Query(False),
    delete_profile: bool = Query(False),
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    profile_owner, profile_tmpl, profile_vol = instance.owner_id, instance.template_id, instance.profile_volume

    # Capture subdomain before deletion for audit
    subdomain = instance.subdomain
    owner_id = instance.owner_id

    if instance.container_id:
        status = await asyncio.to_thread(docker.get_container_status, instance.container_id)
        if status["status"] != "not_found":
            await asyncio.to_thread(docker.remove_container, instance.container_id)

    for vol_name in instance.volume_names:  # remove_volumes is ignored; profile is never listed
        try:
            await asyncio.to_thread(docker.remove_volume, vol_name)
        except Exception:  # noqa: BLE001  volume may already be gone
            logger.warning("could not remove volume %s", vol_name, exc_info=True)

    # Capture template/image before deleting the instance row.
    template = await session.get(ServiceTemplate, instance.template_id)
    image_tag = template.image if template else None
    template_id = instance.template_id

    await record_session_event(session, instance, "destroyed", action="session.stop",
                               reason="deleted")
    await session.delete(instance)
    await session.commit()

    # Audit the instance deletion
    await audit(
        session,
        "instance.delete",
        user_id=user.id,
        resource=instance_id,
        detail={"subdomain": subdomain}
    )
    await session.commit()

    if delete_profile and profile_vol:
        await profiles.delete_after_instance(
            session, docker, Instance(owner_id=profile_owner, template_id=profile_tmpl, name="",
                                      subdomain="", profile_volume=profile_vol), user.id)

    # Opt-in image prune — only when requested AND no other instance uses the image.
    if remove_image and image_tag:
        remaining = await session.exec(
            select(Instance).join(
                ServiceTemplate, col(Instance.template_id) == ServiceTemplate.id
            ).where(ServiceTemplate.image == image_tag)
        )
        if not remaining.first():
            pulled_result = await session.exec(
                select(PulledImage).where(PulledImage.image == image_tag)
            )
            pulled = pulled_result.first()
            if pulled:
                try:
                    await asyncio.to_thread(docker.remove_image, image_tag)
                except Exception:
                    pass
                await session.delete(pulled)
                await session.commit()

    # Opt-in template delete — only when requested AND no other instance uses it.
    if remove_template and template is not None:
        remaining_t = await session.exec(
            select(Instance).where(Instance.template_id == template_id)
        )
        if not remaining_t.first():
            await session.delete(template)
            await session.commit()

    # Clean up per-user network if this was the last instance for the user
    if owner_id:
        remaining_user_instances = await session.exec(
            select(Instance).where(Instance.owner_id == owner_id)
        )
        if not remaining_user_instances.first():
            await asyncio.to_thread(docker.remove_user_network, owner_id)

    await _refresh_routes(session)
    return Response(status_code=204)
