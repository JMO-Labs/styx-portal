import pytest


async def _vals(admin_client):
    r = await admin_client.get("/api/system-settings")
    return {s["key"]: s["value"] for g in r.json() for s in g["settings"]}


async def test_defaults_in_settings_and_public(admin_client, client):
    v = await _vals(admin_client)
    assert (v["brand_name"], v["brand_logo_url"], v["brand_accent"]) == ("Styx", "", "")
    r = await client.get("/api/branding")
    assert r.status_code == 200
    assert r.json() == {"brand_name": "Styx", "brand_logo_url": "", "brand_accent": ""}


async def test_public_endpoint_needs_no_auth_and_reflects_patch(admin_client):
    r = await admin_client.patch("/api/system-settings", json={
        "brand_name": "Acme", "brand_logo_url": "https://x.io/l.png", "brand_accent": "#A1b2C3"})
    assert r.status_code == 200, r.text
    admin_client.cookies.clear()
    r = await admin_client.get("/api/branding")
    assert r.json() == {"brand_name": "Acme", "brand_logo_url": "https://x.io/l.png",
                        "brand_accent": "#A1b2C3"}


@pytest.mark.parametrize("key,value", [
    ("brand_accent", "red"), ("brand_accent", "#12345"), ("brand_accent", "#1234567"),
    ("brand_accent", "123456"), ("brand_logo_url", "http://x.io/l.png"),
    ("brand_logo_url", "javascript:alert(1)"), ("brand_logo_url", "//evil.io/l.png"),
    ("brand_logo_url", "data:image/png;base64,AA"),
])
async def test_invalid_values_422(admin_client, key, value):
    r = await admin_client.patch("/api/system-settings", json={key: value})
    assert r.status_code == 422


@pytest.mark.parametrize("key,value", [
    ("brand_accent", ""), ("brand_logo_url", ""), ("brand_logo_url", "/static/logo.svg"),
    ("brand_logo_url", "https://cdn.x.io/a.png"),
])
async def test_valid_values(admin_client, key, value):
    r = await admin_client.patch("/api/system-settings", json={key: value})
    assert r.status_code == 200, r.text
