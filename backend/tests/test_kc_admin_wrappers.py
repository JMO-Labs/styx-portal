import httpx
import pytest

from app.config import Settings
from app.services import kc_admin
from app.services.kc_admin import KeycloakAdminClient


def _client(handler=None, enabled=True):
    s = Settings(KC_ADMIN_URL="http://kc" if enabled else "", KC_ADMIN_REALM="r",
                 KC_ADMIN_CLIENT_ID="cid", KC_ADMIN_CLIENT_SECRET="sec", JWT_SECRET="x" * 40)
    return KeycloakAdminClient(s, transport=httpx.MockTransport(handler or (lambda r: None)))


async def test_create_user_disabled_returns_empty_id():
    assert await _client(enabled=False).create_user("a.b", "a@b.c", "A", "B") == ""


async def test_get_attributes_disabled_returns_empty():
    assert await _client(enabled=False).get_attributes("u1") == {}


async def test_module_get_attributes_delegates(monkeypatch):
    def h(req: httpx.Request):
        if req.url.path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        return httpx.Response(200, json={"attributes": {"k": ["v"]}})

    monkeypatch.setattr(kc_admin, "_instance", _client(h))
    assert await kc_admin.get_attributes("u1") == {"k": ["v"]}
    kc_admin.reset_client()


@pytest.mark.parametrize("fn,args,method,path", [
    ("create_user", ("a.b", "a@b.c", "A", "B"), "POST", "/admin/realms/r/users"),
    ("update_user", ("u1", {"firstName": "X"}), "PUT", "/admin/realms/r/users/u1"),
    ("set_attributes", ("u1", {"k": ["v"]}), "PUT", "/admin/realms/r/users/u1"),
    ("add_to_group", ("u1", "g1"), "PUT", "/admin/realms/r/users/u1/groups/g1"),
])
async def test_module_wrappers_delegate_to_client(monkeypatch, fn, args, method, path):
    seen = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t", "expires_in": 60})
        seen.append((req.method, req.url.path))
        return httpx.Response(201, headers={"Location": "http://kc/users/new-id"})

    monkeypatch.setattr(kc_admin, "_instance", _client(h))
    result = await getattr(kc_admin, fn)(*args)
    assert seen == [(method, path)]
    if fn == "create_user":
        assert result == "new-id"
    kc_admin.reset_client()
