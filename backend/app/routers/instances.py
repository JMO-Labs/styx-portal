import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session, async_session
from app.models import Instance, ServiceTemplate, PulledImage, User
from app.schemas import InstanceCreate
from app.security.deps import get_current_user, require_owner_or_admin
from app.services.docker_manager import DockerManager
from app.services.k8s_runtime import ensure_instance_supported, instance_runtime
from app.services import gpu_access, instance_readiness, profiles, slo_metrics
from app.services.group_tier import launch_overrides
from app.services.traefik_labels import generate_traefik_labels
from app.services.audit import audit, audit_request
from app.services.session_audit import record_session_event
from app.services.unlock_token import mint_token
from app.services.offboarding import is_disabled
from app.services.settings_store import settings as sys_settings
from app.services.abuse_store import get_abuse_store

logger = logging.getLogger(__name__)

router = APIRouter()
_settings = Settings()

# Parse rate limit config and create instance creation limiter
_limit, _window = _settings.RATE_LIMIT_INSTANCE_CREATE.split("/")


class _CreateLimiter:
    """Instance-create rate limit on the abuse store; fails open (warns) on store errors."""

    def __init__(self, limit: int, window: int) -> None:
        self.limit, self.window = limit, window

    async def allow(self, key: str) -> bool:
        try:
            return await get_abuse_store().rate_allow(f"create:{key}", self.limit, self.window)
        except Exception:
            logger.warning("abuse store failed; allowing instance create", exc_info=True)
            return True


_create_limiter = _CreateLimiter(int(_limit), int(_window))

# Field allowlist for instance updates. Only these fields can be modified via PATCH.
# Re-exports keep `app.routers.instances.<name>` import/patch paths stable.
from app.services.instance_deps import _dind_store_volume, get_docker_manager, get_screenshot_service  # noqa: E402,F401
from app.services.instance_build import (  # noqa: E402,F401
    _refresh_routes, _isolate_or_409, _build_and_start_container,
    _pinned, _egress_kwargs, _home_kwargs)
from app.routers.instance_info import _INSTANCE_UPDATE_FIELDS  # noqa: E402,F401


@router.get("", response_model=list[Instance])
async def list_instances(
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    stmt = select(Instance)
    if user.role != "admin":
        stmt = stmt.where(Instance.owner_id == user.id)
    result = await session.exec(stmt)
    return result.all()


async def _launch_instance_background(instance_id: str, template_id: str, t0: float | None = None):
    """Background task: pull image, create container, start it."""
    docker = instance_runtime()
    async with async_session() as session:
        instance = await session.get(Instance, instance_id)
        template = await session.get(ServiceTemplate, template_id)
        if not instance or not template:
            return

        try:
            needs_pull = await asyncio.to_thread(docker.image_exists, template.image)
            needs_pull = not needs_pull
            instance.status = "pulling" if needs_pull else "starting"
            session.add(instance)
            await session.commit()

            if needs_pull:
                from app.services import pull_progress

                def _cb(pct, detail, _id=instance.id):
                    pull_progress.set_progress(_id, pct, detail)

                try:
                    await asyncio.to_thread(docker.pull_image_streaming, template.image, _cb)
                finally:
                    pull_progress.clear(instance.id)  # never leave stale progress

            volumes = await profiles.prepare_volumes(docker, template, instance)

            if template.dind:
                store = _dind_store_volume(instance.id)
                if store not in instance.volume_names:
                    instance.volume_names = [*instance.volume_names, store]
                await asyncio.to_thread(docker.create_volume, store)
                volumes[store] = {"bind": "/var/lib/docker", "mode": "rw"}

            env, mem_limit, cpu_limit = await launch_overrides(session, docker, instance, template)

            labels = generate_traefik_labels(
                instance_id=instance.id,
                subdomain=instance.subdomain,
                domain=_settings.DOMAIN,
                port=template.internal_port,
                template_name=template.name,
            )

            # Ownerless (legacy) instances get their own network, never styx-portal.
            net = await asyncio.to_thread(docker.ensure_user_network, instance.owner_id or "ownerless")

            container_id = await asyncio.to_thread(
                docker.create_container,
                name=f"selkies-{instance.subdomain}",
                image=template.image,
                labels=labels,
                environment=env,
                volumes=volumes,
                port=template.internal_port,
                gpu_enabled=await gpu_access.resolve_gpu(session, docker, template, instance),
                gpu_count=template.gpu_count,
                memory_limit=mem_limit,
                cpu_limit=cpu_limit,
                shm_size=template.shm_size,
                dind=template.dind,
                cap_add=template.cap_add,
                security_opt=template.security_opt,
                network=net,
                restart_policy=template.restart_policy,
                read_only_rootfs=template.read_only_rootfs,
                tmpfs=template.tmpfs,
                extra_hosts=template.extra_hosts,
                ulimits=template.ulimits,
                devices=template.devices,
                entrypoint=template.entrypoint,
                command=template.command,
                privileged=template.privileged,
                extra_docker_args=template.extra_docker_args,
                **await _home_kwargs(docker, instance, session),
                **await _egress_kwargs(docker, session, instance),
            )

            # Track pulled image
            existing_img = await session.exec(
                select(PulledImage).where(PulledImage.image == template.image)
            )
            if not existing_img.first():
                img_info = await asyncio.to_thread(docker.get_image_info, template.image)
                pulled_img = PulledImage(
                    image=template.image,
                    size_mb=img_info["size_mb"] if img_info else None,
                )
                session.add(pulled_img)

            instance.status = "starting"
            instance.container_id = container_id
            instance.image_digest = _pinned(docker, instance)
            session.add(instance)
            await session.commit()

            await _isolate_or_409(docker, instance, container_id)
            await asyncio.to_thread(docker.start_container, container_id)

            now = datetime.now(timezone.utc)
            instance.status = "running"
            instance.started_at = now
            instance.last_activity = now
            instance_readiness.defer_on_k8s(instance)
            session.add(instance)

            await record_session_event(session, instance, "started", action="session.launch")
            await session.commit()
            instance_readiness.kick(instance, t0, "create")
            await _refresh_routes(session)

        except Exception as e:
            slo_metrics.observe_since("create", "error", t0)
            slo_metrics.record_launch_failure("other")
            logger.error(f"Instance {instance_id} launch failed: {e}")
            instance.status = "error"
            instance.error_message = str(e)
            session.add(instance)
            await record_session_event(session, instance, "error", details={"error": str(e)})
            await session.commit()


@router.post("", response_model=Instance, status_code=201)
async def create_instance(
    body: InstanceCreate,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    if is_disabled(user):
        raise HTTPException(403, "Account disabled")
    template = await session.get(ServiceTemplate, body.template_id)
    if not template:
        raise HTTPException(404, "Template not found")
    ensure_instance_supported(template)

    # Rate limit check for non-admin users
    if user.role != "admin":
        if not await _create_limiter.allow(user.id):
            raise HTTPException(429, "Too many instances created recently — try again later")

        # Quota check for non-admin users
        quota = sys_settings.get("MAX_INSTANCES_PER_USER")
        if quota > 0:
            owned = await session.exec(
                select(Instance).where(Instance.owner_id == user.id)
            )
            owned_count = len(owned.all())
            if owned_count >= quota:
                raise HTTPException(
                    429,
                    f"Instance limit reached ({quota}). Delete an instance first."
                )

    result = await session.exec(
        select(Instance).where(Instance.subdomain == body.subdomain)
    )
    existing = result.first()
    if existing:
        raise HTTPException(409, f"Subdomain '{body.subdomain}' already in use")

    profile_volume = await profiles.claim_profile(session, user.id, template) if body.use_profile else None
    t0 = time.monotonic()
    instance = Instance(
        template_id=template.id,
        owner_id=user.id,
        profile_volume=profile_volume,
        gpu=template.gpu_enabled and body.use_gpu and await gpu_access.user_may_use_gpu(session, user),
        name=body.name,
        subdomain=body.subdomain,
        status="starting",
        env_overrides=body.env_overrides,
        session_config=body.session_config or template.session_config,
    )
    session.add(instance)
    await session.commit()
    await session.refresh(instance)

    # Audit the instance creation
    await audit(
        session,
        "instance.create",
        user_id=user.id,
        resource=instance.id,
        detail={"template": template.name, "subdomain": instance.subdomain}
    )
    await session.commit()

    asyncio.create_task(_launch_instance_background(instance.id, template.id, t0))
    return instance


@router.get("/{instance_id}", response_model=Instance)
async def get_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    return instance


@router.get("/{instance_id}/unlock")
async def unlock_instance(
    instance_id: str,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(get_current_user),
):
    """Mint a 60 s gateway unlock token; needs the HAProxy verified-card header."""
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    reason = None
    if instance.owner_id != user.id and user.role != "admin":
        reason = "not_owner"
    elif not request.headers.get("Client-Cert"):
        reason = "no_card"
    if reason:
        await audit_request(session, request, "session.unlock_denied", user_id=user.id,
                            resource=instance_id, detail={"reason": reason})
        await session.commit()
        raise HTTPException(403, "Card required" if reason == "no_card" else "Not the owner")
    await audit_request(session, request, "session.unlock", user_id=user.id,
                        resource=instance_id)
    await session.commit()
    host = f"{instance.subdomain}.{_settings.DOMAIN}"
    return RedirectResponse(
        f"https://{host}/styx/unlock?token={mint_token(instance_id)}", status_code=302)


@router.post("/{instance_id}/start", response_model=Instance)
async def start_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    t0 = time.monotonic()
    if is_disabled(user):
        raise HTTPException(403, "Account disabled")
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    if instance.status == "running":
        raise HTTPException(409, "Instance already running")
    await profiles.check_instance_profile(session, instance)

    container_exists = False
    if instance.container_id:
        status = await asyncio.to_thread(docker.get_container_status, instance.container_id)
        container_exists = status["status"] != "not_found"

    if container_exists:
        # Reattach Traefik to the per-user network before starting. The network
        # membership is only established on the create/build path, so a Traefik
        # restart leaves it off the net and routing 502s until reattached.
        await _isolate_or_409(docker, instance, instance.container_id)
        await asyncio.to_thread(docker.start_container, cast(str, instance.container_id))
    else:
        template = await session.get(ServiceTemplate, instance.template_id)
        if not template:
            raise HTTPException(400, "Template no longer exists, cannot recreate")

        try:
            await _build_and_start_container(instance, template, docker, session)
        except ValueError as e:
            raise HTTPException(422, f"Template volumes invalid: {e}")

    now = datetime.now(timezone.utc)
    instance.status = "running"
    instance.started_at = now
    instance.last_activity = now
    instance_readiness.defer_on_k8s(instance)
    session.add(instance)

    await record_session_event(session, instance, "started", action="session.launch",
                               details={"recreated": not container_exists})
    await session.commit()
    await session.refresh(instance)
    instance_readiness.kick(instance, t0, "start")
    await _refresh_routes(session)
    return instance


@router.post("/{instance_id}/stop", response_model=Instance)
async def stop_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)

    if instance.container_id:
        status = await asyncio.to_thread(docker.get_container_status, instance.container_id)
        if status["status"] not in ("not_found", "exited"):
            await asyncio.to_thread(docker.stop_container, instance.container_id)

    instance.status = "stopped"
    instance.stopped_at = datetime.now(timezone.utc)
    session.add(instance)

    await record_session_event(session, instance, "stopped", action="session.stop", reason="user")
    await session.commit()
    await session.refresh(instance)
    await _refresh_routes(session)
    return instance


@router.post("/{instance_id}/restart", response_model=Instance)
async def restart_instance(
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
    if not instance.container_id:
        raise HTTPException(400, "No container to restart")

    # Reattach Traefik to the per-user network (see start_instance) — a Traefik
    # restart drops its membership and routing 502s until reattached.
    await _isolate_or_409(docker, instance, instance.container_id)
    await asyncio.to_thread(docker.restart_container, instance.container_id)

    now = datetime.now(timezone.utc)
    instance.status = "running"
    instance.started_at = now
    instance.last_activity = now
    instance.error_message = None
    instance_readiness.defer_on_k8s(instance)
    session.add(instance)

    await record_session_event(session, instance, "restarted")
    await session.commit()
    await session.refresh(instance)
    instance_readiness.kick(instance, t0, "start")
    return instance


@router.post("/{instance_id}/recreate", response_model=Instance)
async def recreate_instance(
    instance_id: str,
    session: AsyncSession = Depends(get_session),
    docker: DockerManager = Depends(get_docker_manager),
    user: User = Depends(get_current_user),
):
    """Rebuild the instance's container from its (updated) template, reusing the
    instance's named volumes so persistent data is preserved. Same instance id/subdomain."""
    t0 = time.monotonic()
    instance = await session.get(Instance, instance_id)
    if not instance:
        raise HTTPException(404, "Instance not found")
    require_owner_or_admin(instance.owner_id, user)
    template = await session.get(ServiceTemplate, instance.template_id)
    if not template:
        raise HTTPException(400, "Template no longer exists, cannot recreate")
    await profiles.check_instance_profile(session, instance)

    # Remove the old container, keep volumes.
    if instance.container_id:
        status = await asyncio.to_thread(docker.get_container_status, instance.container_id)
        if status["status"] != "not_found":
            if status["status"] not in ("exited",):
                await asyncio.to_thread(docker.stop_container, instance.container_id)
            await asyncio.to_thread(docker.remove_container, instance.container_id)

    # Volume names are recomputed from the (possibly updated) template; instance.id is stable,
    # so unchanged defs reuse the existing volume (data preserved).
    try:
        await _build_and_start_container(instance, template, docker, session)
    except ValueError as e:
        raise HTTPException(422, f"Template volumes invalid: {e}")

    now = datetime.now(timezone.utc)
    instance.status = "running"
    instance.started_at = now
    instance.last_activity = now
    instance.error_message = None
    instance_readiness.defer_on_k8s(instance)
    session.add(instance)

    await record_session_event(session, instance, "recreated")
    await session.commit()
    await session.refresh(instance)
    instance_readiness.kick(instance, t0, "start")
    await _refresh_routes(session)
    return instance


from app.routers import instance_info, instance_ops  # noqa: E402

router.include_router(instance_ops.router)
router.include_router(instance_info.router)
