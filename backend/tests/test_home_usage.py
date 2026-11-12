import httpx
import pytest

from app.config import Settings
from app.services import home_usage as hu


def _transport(used, cap, fail=False):
    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            return httpx.Response(500)
        q = request.url.params["query"]
        assert "home-123" in q
        val = used if "used_bytes" in q else cap
        return httpx.Response(200, json={"status": "success", "data": {
            "result": [{"value": [0, str(val)]}]}})
    return httpx.MockTransport(handler)


async def test_home_usage_computes_percent():
    r = await hu.home_usage(123, "http://prom", transport=_transport(5, 10))
    assert r == {"used_bytes": 5, "quota_bytes": 10, "percent": 50.0}


async def test_home_usage_empty_url_returns_none():
    assert await hu.home_usage(123, "") is None


async def test_home_usage_failure_returns_none():
    assert await hu.home_usage(123, "http://prom", transport=_transport(1, 1, fail=True)) is None


async def test_home_usage_no_series_returns_none():
    t = httpx.MockTransport(lambda r: httpx.Response(
        200, json={"status": "success", "data": {"result": []}}))
    assert await hu.home_usage(123, "http://prom", transport=t) is None


def test_setting_default_empty():
    assert Settings().PROMETHEUS_URL == ""


@pytest.mark.parametrize("pct,warn", [(79, False), (80, True)])
async def test_endpoint_warn_threshold(member_client, monkeypatch, pct, warn):
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom")
    async def fake(uid, url, **kw):
        return {"used_bytes": pct, "quota_bytes": 100, "percent": float(pct)}
    monkeypatch.setattr("app.routers.me_storage.home_usage", fake)
    r = await member_client.get("/api/me/storage")
    assert r.status_code == 200
    assert r.json() == {"used_bytes": pct, "quota_bytes": 100, "percent": float(pct), "warn": warn}


async def test_endpoint_unavailable(member_client):
    r = await member_client.get("/api/me/storage")
    assert r.status_code == 200
    assert r.json() == {"used_bytes": None, "quota_bytes": None, "percent": None, "warn": False}


async def test_endpoint_requires_login(client):
    assert (await client.get("/api/me/storage")).status_code == 401


async def test_endpoint_url_set_but_no_usage(member_client, monkeypatch):
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom")

    async def fake(uid, url, **kw):
        return None
    monkeypatch.setattr("app.routers.me_storage.home_usage", fake)
    r = await member_client.get("/api/me/storage")
    assert r.status_code == 200
    assert r.json() == {"used_bytes": None, "quota_bytes": None, "percent": None, "warn": False}
