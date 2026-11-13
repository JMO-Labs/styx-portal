"""Pre-pull instance images on every node via a DaemonSet of pull-only initContainers."""
import asyncio
import hashlib
import logging
from datetime import datetime, timezone

from sqlmodel import select

from app.config import Settings
from app.models import ServiceTemplate, User
from app.services.image_digest import digest_of, resolve_digest
from app.services.k8s_instance_objects import MANAGED, refuse_reason

logger = logging.getLogger("styx-portal")
PREFIX = "styx-prepull-"
_RES = {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"cpu": "10m", "memory": "16Mi"}}
_SEC = {"runAsNonRoot": True, "runAsUser": 65534, "runAsGroup": 65534,
        "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]}}
_bg: set[asyncio.Task] = set()


def prepull_name(image: str) -> str:
    return PREFIX + hashlib.sha1(image.encode(), usedforsecurity=False).hexdigest()[:10]


def build_prepull_daemonset(image: str, ns: str, stamp: str | None = None) -> dict:
    stamp = stamp or datetime.now(timezone.utc).isoformat()
    name = prepull_name(image)
    labels = {"app": name, "styx/prepull": "true", **MANAGED}
    # ponytail: images whose shell lacks sh (or can't run as 65534) fail the initContainer; add a per-template pull-only flag if that happens
    init = {"name": "img", "image": image, "imagePullPolicy": "Always",
            "command": ["sh", "-c", "exit 0"], "resources": _RES, "securityContext": dict(_SEC)}
    pod = {"automountServiceAccountToken": False, "enableServiceLinks": False,
           "securityContext": {"seccompProfile": {"type": "RuntimeDefault"}},
           "initContainers": [init],
           "containers": [{"name": "pause", "image": "registry.k8s.io/pause:3.10",
                           "resources": _RES, "securityContext": dict(_SEC)}]}
    meta = {"name": name, "namespace": ns, "labels": {"styx/prepull": "true", **MANAGED}}
    digest = digest_of(image)
    if digest:
        repo = image.split("@", 1)[0]
        meta["labels"]["styx/prepull-repo"] = _repo_key(repo)
        meta["annotations"] = {"styx/prepull-digest": digest}
    return {"apiVersion": "apps/v1", "kind": "DaemonSet", "metadata": meta,
            "spec": {"selector": {"matchLabels": {"app": name}},
                     "template": {"metadata": {"labels": labels,
                                               "annotations": {"styx/prepull-at": stamp}},
                                  "spec": pod}}}


def _repo_key(repo: str) -> str:
    return hashlib.sha1(repo.encode(), usedforsecurity=False).hexdigest()[:10]


def _is_ready(ds: dict) -> bool:
    st = ds.get("status") or {}
    desired = st.get("desiredNumberScheduled") or 0
    return desired > 0 and (st.get("numberReady") or 0) >= desired


def _ds_digest(ds: dict) -> str | None:
    return ((ds.get("metadata") or {}).get("annotations") or {}).get("styx/prepull-digest")


def ready_digest(client, ns: str, resolved: str) -> str:
    """`resolved`, unless its prepull DaemonSet is still pulling: then the newest
    fully-ready older digest of the same repo. Never blocks: falls back to `resolved`."""
    digest = digest_of(resolved)
    if not digest:
        return resolved
    repo = resolved.split("@", 1)[0]
    try:
        items = client.list_items("apps/v1", "DaemonSet", ns,
                                  f"styx/prepull-repo={_repo_key(repo)}")
        ready = [d for d in items if _is_ready(d) and _ds_digest(d)]
        if any(_ds_digest(d) == digest for d in ready):
            return resolved
        ready.sort(key=lambda d: d["metadata"].get("creationTimestamp", ""), reverse=True)
        return f"{repo}@{_ds_digest(ready[0])}" if ready else resolved
    except Exception:  # noqa: BLE001 - never block a launch
        logger.warning("prepull readiness check failed", exc_info=True)
        return resolved


def prepull_images(templates) -> list[str]:
    out: list[str] = []
    for t in templates:
        if refuse_reason(t):
            continue
        img = t.image if "/" in t.image else Settings().K8S_DESKTOP_IMAGE
        img = resolve_digest(img)
        if img not in out:
            out.append(img)
    return out


async def sync_prepull(session) -> None:
    if Settings().ROUTE_BACKEND != "k8s":
        return
    from app.services.k8s_api import incluster_client
    # only shared or admin-owned templates: member templates pull at launch
    rows = await session.exec(
        select(ServiceTemplate).outerjoin(User, ServiceTemplate.owner_id == User.id)
        .where((ServiceTemplate.owner_id.is_(None)) | (User.role == "admin")))
    ns = Settings().K8S_INSTANCE_NAMESPACE
    templates = rows.all()
    # resolve_digest does blocking HTTP: keep it off the event loop
    images = await asyncio.to_thread(prepull_images, templates)
    desired = {prepull_name(i): i for i in images}
    client = incluster_client()

    def _apply() -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        for img in desired.values():
            client.apply(build_prepull_daemonset(img, ns, stamp))
        items = client.list_items("apps/v1", "DaemonSet", ns, "styx/prepull=true")
        # an old digest stays until the newer one for the same repo is fully ready
        pulling = {(d["metadata"].get("labels") or {}).get("styx/prepull-repo")
                   for d in items if d["metadata"]["name"] in desired and not _is_ready(d)}
        for d in items:
            name = d["metadata"]["name"]
            repo = (d["metadata"].get("labels") or {}).get("styx/prepull-repo")
            if name not in desired and not (repo and repo in pulling):
                client.delete("apps/v1", "DaemonSet", ns, name)
    await asyncio.to_thread(_apply)


async def _sync_own_session() -> None:
    from app.database import async_session
    try:
        async with async_session() as session:
            await sync_prepull(session)
    except Exception:  # noqa: BLE001 - best effort
        logger.warning("image prepull sync failed", exc_info=True)


def schedule_sync() -> None:
    """Fire-and-forget sync (after template changes); no-op off k8s."""
    if Settings().ROUTE_BACKEND != "k8s":
        return
    t = asyncio.create_task(_sync_own_session())
    _bg.add(t)
    t.add_done_callback(_bg.discard)


async def prepull_loop() -> None:
    """Sync at startup, then every PREPULL_INTERVAL_S (picks up newly signed digests)."""
    while True:
        await _sync_own_session()
        await asyncio.sleep(Settings().PREPULL_INTERVAL_S)
