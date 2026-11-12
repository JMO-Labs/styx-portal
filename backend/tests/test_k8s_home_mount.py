from unittest.mock import MagicMock

from app.config import Settings
from app.services.k8s_instance_objects import build_objects
from app.services.k8s_instances import K8sInstanceRuntime

NS = "styx-instances"


def _pod(uid=None, name="selkies-a"):
    dep = build_objects(name, "img/x:1", {}, {}, 3000, NS, "o", posix_uid=uid)[0]
    return dep["spec"]["template"]["spec"]


def test_security_context_runs_as_uid():
    sc = _pod(2001)["securityContext"]
    assert sc["runAsUser"] == sc["runAsGroup"] == sc["fsGroup"] == 2001
    assert sc["runAsNonRoot"] is True
    assert sc["seccompProfile"] == {"type": "RuntimeDefault"}


def test_no_uid_leaves_context_unchanged():
    sc = _pod()["securityContext"]
    assert "runAsUser" not in sc and "fsGroup" not in sc
    assert not _pod()["volumes"]


def test_home_pvc_mounted_at_home_mount_path(monkeypatch):
    spec = _pod(2001)
    vol = next(v for v in spec["volumes"] if v["name"] == "home")
    assert vol["persistentVolumeClaim"]["claimName"] == "home-2001"
    m = next(m for m in spec["containers"][0]["volumeMounts"] if m["name"] == "home")
    assert m["mountPath"] == Settings().HOME_MOUNT_PATH == "/home/user"
    monkeypatch.setenv("HOME_MOUNT_PATH", "/config")
    spec = _pod(2001)
    m = next(m for m in spec["containers"][0]["volumeMounts"] if m["name"] == "home")
    assert m["mountPath"] == "/config"


def test_users_reference_only_their_own_claim():
    a, b = _pod(2001, "selkies-a"), _pod(2002, "selkies-b")

    def claims(p):
        return {v["persistentVolumeClaim"]["claimName"]
                for v in p["volumes"] if "persistentVolumeClaim" in v}

    assert claims(a) == {"home-2001"} and claims(b) == {"home-2002"}
    assert a["securityContext"]["runAsUser"] != b["securityContext"]["runAsUser"]


def test_create_container_ensures_home_before_apply_and_scale_up():
    c = MagicMock()
    c.get_json.return_value = None
    calls = []
    c.apply.side_effect = lambda o: calls.append(("apply", o["kind"], o["metadata"]["name"]))
    c.patch_merge.side_effect = lambda *a, **k: calls.append(("scale",))
    rt = K8sInstanceRuntime(client=c)
    rt.create_container("selkies-a", "img/x:1", [], {}, {}, 3000, posix_uid=2001)
    rt.start_container("selkies-a")
    assert calls[0] == ("apply", "PersistentVolumeClaim", "home-2001")
    assert calls[-1] == ("scale",)
    dep = next(o for o in (x.args[0] for x in c.apply.call_args_list)
               if o["kind"] == "Deployment")
    assert dep["spec"]["template"]["spec"]["securityContext"]["runAsUser"] == 2001


async def test_home_kwargs_k8s_owner_gets_stable_allocated_uid(session):
    from types import SimpleNamespace

    from app.routers.instances import _home_kwargs
    from app.services.posix_uid import allocate_uid

    rt = K8sInstanceRuntime(client=MagicMock())
    inst = SimpleNamespace(owner_id="user-1")
    got = await _home_kwargs(rt, inst, session)
    assert got == {"posix_uid": await allocate_uid(session, "user-1"),
                   "home_read_only": False}
    assert await _home_kwargs(rt, inst, session) == got


async def test_home_kwargs_ownerless_is_empty(session):
    from types import SimpleNamespace

    from app.routers.instances import _home_kwargs

    rt = K8sInstanceRuntime(client=MagicMock())
    assert await _home_kwargs(rt, SimpleNamespace(owner_id=None), session) == {}


async def test_home_kwargs_docker_runtime_is_empty(session):
    from types import SimpleNamespace

    from app.routers.instances import _home_kwargs

    assert await _home_kwargs(MagicMock(), SimpleNamespace(owner_id="user-1"), session) == {}
