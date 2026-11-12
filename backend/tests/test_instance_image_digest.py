"""AC2: launch paths persist the k8s-pinned digest on the instance row (#147)."""
from unittest.mock import AsyncMock, MagicMock, patch

from app.models import Instance, ServiceTemplate, User
from app.routers.instances import _build_and_start_container, _launch_instance_background


def runtime(digest):
    rt = MagicMock()
    rt.create_container.return_value = "cid"
    rt.create_volume.side_effect = lambda name, size=None: name
    rt.image_exists.return_value = True
    rt.pull_image_streaming = AsyncMock()
    rt.get_image_info.return_value = {"size_mb": 1}
    if digest is None:
        del rt.pinned_digest  # Docker runtime has no pinned_digest
    else:
        rt.pinned_digest.return_value = digest
    return rt


async def _build(digest):
    inst = Instance(template_id="t", owner_id=None, name="n", subdomain="n")
    tmpl = ServiceTemplate(name="t", display_name="t", image="x")
    rt = runtime(digest)
    await _build_and_start_container(inst, tmpl, rt, None)
    return inst, rt


async def test_build_and_start_stores_k8s_digest():
    inst, rt = await _build("sha256:new")
    assert inst.image_digest == "sha256:new"
    rt.pinned_digest.assert_called_once_with("selkies-n")


async def test_build_and_start_docker_leaves_none():
    inst, _ = await _build(None)
    assert inst.image_digest is None


async def _background(session, digest):
    tmpl = ServiceTemplate(name="dg", display_name="dg", image="x:latest")
    user = User(username="dg", password_hash="x", role="admin", is_active=True)
    session.add_all([tmpl, user])
    await session.commit()
    inst = Instance(template_id=tmpl.id, owner_id=user.id, name="dg", subdomain="dg",
                    status="starting", volume_names=[])
    session.add(inst)
    await session.commit()

    class Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *a):
            pass

    rt = runtime(digest)
    with patch("app.routers.instances.instance_runtime", return_value=rt), \
         patch("app.routers.instances.async_session", lambda: Ctx()):
        await _launch_instance_background(inst.id, tmpl.id)
    rt.start_container.assert_called_once_with("cid")
    return (await session.get(Instance, inst.id, populate_existing=True)).image_digest


async def test_background_launch_persists_k8s_digest(session):
    assert await _background(session, "sha256:new") == "sha256:new"


async def test_background_launch_docker_digest_none(session):
    assert await _background(session, None) is None
