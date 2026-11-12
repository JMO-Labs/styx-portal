from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.routers import instances
from app.services.k8s_instance_objects import build_objects
from app.services.k8s_instances import K8sInstanceRuntime

HOST = "squid.egress-proxy.svc.cluster.local"
NO_PROXY = "localhost,127.0.0.1,.svc,.cluster.local"


def _build(**kw):
    dep, _ = build_objects("selkies-a", "selkies:latest", {}, {}, 3000, "ns", "u1", **kw)
    return dep, dep["spec"]["template"]["spec"]["containers"][0]


def _env(c):
    return {e["name"]: e["value"] for e in c["env"]}


@pytest.mark.parametrize("mode,port", [("category", 3128), ("allowlist", 3129)])
def test_label_and_proxy_env(mode, port):
    dep, c = _build(egress_mode=mode)
    for labels in (dep["metadata"]["labels"], dep["spec"]["template"]["metadata"]["labels"]):
        assert labels["styx.io/egress-mode"] == mode
    env = _env(c)
    url = f"http://{HOST}:{port}"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        assert env[k] == url
    assert env["NO_PROXY"] == env["no_proxy"] == NO_PROXY


def test_no_mode_no_proxy():
    dep, c = _build()
    assert "styx.io/egress-mode" not in dep["metadata"]["labels"]
    assert "HTTP_PROXY" not in _env(c)


def test_runtime_passes_mode_through():
    rt = K8sInstanceRuntime(client=MagicMock())
    with patch("app.services.k8s_instances.build_objects", return_value=[]) as b:
        rt.create_container("n", "i", {}, {}, {}, 3000, egress_mode="allowlist")
    assert b.call_args.kwargs["egress_mode"] == "allowlist"


@pytest.mark.asyncio
async def test_kwargs_k8s_resolves_owner_mode():
    rt = K8sInstanceRuntime(client=MagicMock())
    session = MagicMock()
    session.get = AsyncMock(return_value=SimpleNamespace(id="u1"))
    with patch("app.routers.instances.resolve_egress_mode",
               AsyncMock(return_value="allowlist")):
        out = await instances._egress_kwargs(rt, session, SimpleNamespace(owner_id="u1"))
    assert out == {"egress_mode": "allowlist"}


@pytest.mark.asyncio
async def test_kwargs_docker_empty():
    out = await instances._egress_kwargs(MagicMock(), MagicMock(),
                                         SimpleNamespace(owner_id="u1"))
    assert out == {}
