"""Container (re)build helpers for instance lifecycle routes."""
import asyncio
import logging

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.services import gpu_access, profiles
from app.services.instance_deps import _dind_store_volume
from app.services.k8s_runtime import ensure_instance_supported
from app.services.traefik_labels import generate_traefik_labels

logger = logging.getLogger(__name__)
_settings = Settings()


async def _refresh_routes(session: AsyncSession):
    from app.services.route_writer import refresh_routes_from_db

    await refresh_routes_from_db(session)


async def _isolate_or_409(docker, instance, container_id):
    """Fail closed: never start an instance container that may share styx-portal with the backend."""
    try:
        await asyncio.to_thread(docker.ensure_isolated, container_id, instance.owner_id)
    except Exception:  # noqa: BLE001
        logger.error("could not isolate instance %s network", instance.name, exc_info=True)
        raise HTTPException(409, "Instance network could not be isolated")


async def _build_and_start_container(instance, template, docker, session):
    """(Re)create the Docker container for an instance from its template,
    mounting the instance's existing named volumes (data preserved), then start it.
    Sets instance.container_id. Caller commits."""
    ensure_instance_supported(template)
    volumes = await profiles.prepare_volumes(docker, template, instance)

    if template.dind:
        store = _dind_store_volume(instance.id)
        if store not in instance.volume_names:
            instance.volume_names = [*instance.volume_names, store]
        await asyncio.to_thread(docker.create_volume, store)
        volumes[store] = {"bind": "/var/lib/docker", "mode": "rw"}

    env = {**template.env_vars, **(instance.env_overrides or {})}
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
        memory_limit=template.memory_limit,
        cpu_limit=template.cpu_limit,
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
    )
    try:
        await _isolate_or_409(docker, instance, container_id)
    except HTTPException:
        await asyncio.to_thread(docker.remove_container, container_id)
        raise
    instance.container_id = container_id
    await asyncio.to_thread(docker.start_container, container_id)
    return container_id
