"""Freeze home read-only on account disable (#159, ADR-0034/0022)."""
from unittest.mock import MagicMock

import httpx
import pytest

from app.models import PosixUid, User
from app.services.k8s_homes import freeze_home
from app.services.k8s_instance_objects import build_objects
from app.services.k8s_instances import K8sInstanceRuntime
from app.services.offboarding import disable_account

NS = "styx-instances"


def _err(code):
    req = httpx.Request("PATCH", "http://k/x")
    return httpx.HTTPStatusError("e", request=req, response=httpx.Response(code, request=req))


def _mount(**kw):
    dep = build_objects("selkies-a", "img/x:1", {}, {}, 3000, NS, "o", posix_uid=2001, **kw)[0]
    c = dep["spec"]["template"]["spec"]["containers"][0]
    return next(m for m in c["volumeMounts"] if m["name"] == "home")


def test_home_rw_by_default():
    assert not _mount().get("readOnly")


def test_home_read_only_when_frozen():
    assert _mount(home_read_only=True)["readOnly"] is True


def test_runtime_passes_home_read_only():
    api = MagicMock()
    api.get_json.return_value = {}
    K8sInstanceRuntime(client=api).create_container(
        "selkies-a", "img/x:1", {}, {}, {}, 3000, posix_uid=2001, home_read_only=True)
    dep = next(c.args[0] for c in api.apply.call_args_list if c.args[0]["kind"] == "Deployment")
    m = dep["spec"]["template"]["spec"]["containers"][0]["volumeMounts"]
    assert next(x for x in m if x["name"] == "home")["readOnly"] is True


def test_freeze_home_patches_label():
    api = MagicMock()
    freeze_home(api, 2001, NS)
    api.patch_merge.assert_called_once_with(
        "v1", "PersistentVolumeClaim", NS, "home-2001",
        {"metadata": {"labels": {"styx/home-frozen": "true"}}})


def test_freeze_home_idempotent():
    api = MagicMock()
    freeze_home(api, 2001, NS)
    freeze_home(api, 2001, NS)
    assert api.patch_merge.call_count == 2
    assert api.patch_merge.call_args_list[0] == api.patch_merge.call_args_list[1]


def test_freeze_home_missing_pvc_is_ok():
    api = MagicMock()
    api.patch_merge.side_effect = _err(404)
    freeze_home(api, 2001, NS)


def test_freeze_home_other_errors_raise():
    api = MagicMock()
    api.patch_merge.side_effect = _err(500)
    with pytest.raises(httpx.HTTPStatusError):
        freeze_home(api, 2001, NS)


async def test_disable_account_freezes_home_in_k8s(session, monkeypatch):
    monkeypatch.setenv("ROUTE_BACKEND", "k8s")
    u = User(username="bob", password_hash="x")
    session.add(u)
    await session.commit()
    session.add(PosixUid(uid=2001, user_key=u.id))
    await session.commit()
    rt = MagicMock()
    await disable_account(session, u, "r", "a", runtime=rt)
    rt._c.patch_merge.assert_called_once()
    assert rt._c.patch_merge.call_args.args[3] == "home-2001"


async def test_disable_account_no_freeze_outside_k8s(session):
    u = User(username="amy", password_hash="x")
    session.add(u)
    await session.commit()
    rt = MagicMock()
    await disable_account(session, u, "r", "a", runtime=rt)
    rt._c.patch_merge.assert_not_called()


@pytest.mark.parametrize("active", [True, False])
async def test_start_path_sets_home_read_only(session, active):
    from app.routers.instances import _home_kwargs
    u = User(username=f"u{active}", password_hash="x", is_active=active)
    session.add(u)
    await session.commit()
    inst = MagicMock(owner_id=u.id)
    kw = await _home_kwargs(MagicMock(spec=K8sInstanceRuntime), inst, session)
    assert kw["home_read_only"] is (not active)
