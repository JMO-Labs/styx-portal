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
