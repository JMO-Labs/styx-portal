import json
import logging

import httpx
import pytest

from app.config import Settings
from app.services.kc_admin import KeycloakAdminClient, KeycloakAdminError, make_username


def make(handler, admin_groups=""):
    s = Settings(KC_ADMIN_URL="http://kc", KC_ADMIN_REALM="r", KC_ADMIN_CLIENT_ID="cid",
                 KC_ADMIN_CLIENT_SECRET="s3cr3t-value", KEYCLOAK_ADMIN_GROUPS=admin_groups,
                 JWT_SECRET="x" * 40)
    return KeycloakAdminClient(s, transport=httpx.MockTransport(handler), clock=lambda: 1000.0)


def recorder(status=204, headers=None):
    seen = []

    def h(req: httpx.Request):
        if req.url.path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "tok", "expires_in": 60})
        seen.append((req.method, req.url.path, json.loads(req.content) if req.content else None))
        return httpx.Response(status, headers=headers or {})

    return h, seen


async def test_create_user_returns_id_from_location():
    h, seen = recorder(201, {"Location": "http://kc/admin/realms/r/users/new-id"})
    uid = await make(h).create_user("ada.lovelace", "ada@x.io", "Ada", "Lovelace")
    assert uid == "new-id"
    m, p, body = seen[0]
    assert (m, p) == ("POST", "/admin/realms/r/users")
    assert body == {"username": "ada.lovelace", "email": "ada@x.io", "firstName": "Ada",
                    "lastName": "Lovelace", "enabled": True}


async def test_update_user():
    h, seen = recorder()
    await make(h).update_user("u1", {"email": "n@x.io"})
    assert seen[0] == ("PUT", "/admin/realms/r/users/u1", {"email": "n@x.io"})


async def test_set_attributes():
    h, seen = recorder()
    await make(h).set_attributes("u1", {"card": ["42"]})
    assert seen[0] == ("PUT", "/admin/realms/r/users/u1", {"attributes": {"card": ["42"]}})


async def test_add_to_group():
    h, seen = recorder()
    await make(h).add_to_group("u1", "g1")
    assert seen[0] == ("PUT", "/admin/realms/r/users/u1/groups/g1", None)


async def test_add_to_admin_group_refused_without_calling_keycloak():
    h, seen = recorder()
    c = make(h, admin_groups="gA, gAdmin")
    with pytest.raises(KeycloakAdminError):
        await c.add_to_group("u1", "gAdmin")
    assert seen == []


async def test_secret_never_logged(caplog):
    caplog.set_level(logging.DEBUG)
    h, _ = recorder()
    c = make(h)
    await c.add_to_group("u1", "g1")
    await c.update_user("u1", {"email": "a@b.c"})
    assert "s3cr3t-value" not in caplog.text


def test_username_basic_and_normalised():
    assert make_username("Ada", "Lovelace", set()) == "ada.lovelace"
    assert make_username("Zoë", "O'Brien", set()) == "zoe.obrien"


def test_username_collision_appends_digit():
    assert make_username("Ada", "Lovelace", {"ada.lovelace"}) == "ada.lovelace1"
    assert make_username("Ada", "Lovelace", {"ada.lovelace", "ada.lovelace1"}) == "ada.lovelace2"
