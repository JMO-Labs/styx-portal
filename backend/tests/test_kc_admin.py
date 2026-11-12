import json
import logging

import httpx
import pytest

from app.config import Settings
from app.services import kc_admin
from app.services.kc_admin import KeycloakAdminClient, KeycloakAdminError


def make(handler, **kw):
    s = Settings(KC_ADMIN_URL="http://kc", KC_ADMIN_REALM="r",
                 KC_ADMIN_CLIENT_ID="cid", KC_ADMIN_CLIENT_SECRET="sec", JWT_SECRET="x" * 40)
    clock = kw.get("clock", lambda: 1000.0)
    return KeycloakAdminClient(s, transport=httpx.MockTransport(handler), clock=clock)


def recorder(status=204, token_calls=None):
    seen = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/protocol/openid-connect/token"):
            seen.append(("TOKEN", req.url.path, req.content.decode()))
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 60})
        seen.append((req.method, req.url.path, req.content, req.headers.get("authorization")))
        return httpx.Response(status)

    return h, seen


async def test_disable_user():
    h, seen = recorder()
    await make(h).disable_user("u1")
    assert seen[0][0] == "TOKEN"
    assert seen[0][1] == "/realms/r/protocol/openid-connect/token"
    assert "grant_type=client_credentials" in seen[0][2]
    m, p, body, auth = seen[1]
    assert (m, p) == ("PUT", "/admin/realms/r/users/u1")
    assert json.loads(body) == {"enabled": False}
    assert auth == "Bearer tok"


async def test_delete_user():
    h, seen = recorder()
    await make(h).delete_user("u1")
    assert seen[1][:2] == ("DELETE", "/admin/realms/r/users/u1")


async def test_remove_from_group():
    h, seen = recorder()
    await make(h).remove_from_group("u1", "g1")
    assert seen[1][:2] == ("DELETE", "/admin/realms/r/users/u1/groups/g1")
    assert not any("role-mappings" in s[1] for s in seen)


async def test_token_cached_until_expiry():
    h, seen = recorder()
    now = [1000.0]
    c = make(h, clock=lambda: now[0])
    await c.delete_user("a")
    await c.delete_user("b")
    assert [s[0] for s in seen].count("TOKEN") == 1
    now[0] += 120
    await c.delete_user("c")
    assert [s[0] for s in seen].count("TOKEN") == 2


async def test_non_2xx_raises():
    h, _ = recorder(status=500)
    with pytest.raises(KeycloakAdminError):
        await make(h).disable_user("u1")


async def test_token_failure_raises():
    c = make(lambda r: httpx.Response(401))
    with pytest.raises(KeycloakAdminError):
        await c.delete_user("u1")


async def test_404_is_success():
    h, _ = recorder(status=404)
    c = make(h)
    await c.delete_user("u1")
    await c.disable_user("u1")


async def test_404_group_removal_is_success():
    h, _ = recorder(status=404)
    await make(h).remove_from_group("u1", "g1")


async def test_unconfigured_skips_and_logs(caplog):
    def boom(req):
        raise AssertionError("no http expected")

    s = Settings(JWT_SECRET="x" * 40)
    c = KeycloakAdminClient(s, transport=httpx.MockTransport(boom))
    with caplog.at_level(logging.INFO):
        await c.disable_user("u1")
        await c.delete_user("u1")
        await c.remove_from_group("u1", "g")
    assert caplog.text.count("kc_admin.disabled") == 3


def test_no_role_mapping_api():
    import inspect

    assert "role-mappings" not in inspect.getsource(kc_admin)
    assert not [n for n in dir(KeycloakAdminClient) if "role" in n]


async def test_encoded_path_raw():
    paths = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        paths.append(req.url.raw_path.decode())
        return httpx.Response(204)

    await make(h).remove_from_group("a/../b", "g/x")
    assert paths == ["/admin/realms/r/users/a%2F..%2Fb/groups/g%2Fx"]


async def test_module_level_calls_share_one_client_and_token():
    tokens = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/token"):
            tokens.append(1)
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        return httpx.Response(204)

    kc_admin.reset_client()
    kc_admin._instance = make(h)
    try:
        await kc_admin.disable_user("u1")
        await kc_admin.delete_user("u1")
    finally:
        kc_admin.reset_client()
    assert len(tokens) == 1


async def test_module_remove_from_group_delegates():
    paths = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        paths.append((req.method, req.url.path))
        return httpx.Response(204)

    kc_admin.reset_client()
    kc_admin._instance = make(h)
    try:
        await kc_admin.remove_from_group("u1", "g1")
    finally:
        kc_admin.reset_client()
    assert paths == [("DELETE", "/admin/realms/r/users/u1/groups/g1")]


def test_client_lazily_builds_singleton(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    kc_admin.reset_client()
    try:
        first = kc_admin._client()
        assert isinstance(first, KeycloakAdminClient)
        assert kc_admin._client() is first
    finally:
        kc_admin.reset_client()
