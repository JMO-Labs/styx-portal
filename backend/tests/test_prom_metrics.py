import pytest
from prometheus_client import REGISTRY

NAME = "styx_http_request_duration_seconds_count"


def _count(method, route, status):
    return REGISTRY.get_sample_value(NAME, {"method": method, "route": route, "status": str(status)}) or 0.0


async def test_route_template_label(client):
    before = _count("GET", "/api/instances/{instance_id}", 401)
    r = await client.get("/api/instances/abc123")
    assert r.status_code == 401
    seen = sorted(
        (x.labels["route"], x.labels["status"], x.value)
        for m in REGISTRY.collect() if m.name == "styx_http_request_duration_seconds"
        for x in m.samples if x.name == NAME and x.labels["method"] == "GET" and "instances" in x.labels["route"]
    )
    assert _count("GET", "/api/instances/{instance_id}", 401) == before + 1, seen
    assert _count("GET", "/api/instances/abc123", 401) == 0


async def test_unmatched_route_label(client):
    before = _count("GET", "unmatched", 404)
    for i in range(3):
        await client.get(f"/no/such/path/{i}")
    assert _count("GET", "unmatched", 404) == before + 3
    assert _count("GET", "/no/such/path/0", 404) == 0


async def test_exception_recorded_as_500():
    from app.services.prom_metrics import PrometheusMiddleware

    async def boom(scope, receive, send):
        raise RuntimeError("x")

    before = _count("GET", "unmatched", 500)
    mw = PrometheusMiddleware(boom)
    with pytest.raises(RuntimeError):
        await mw({"type": "http", "method": "GET", "path": "/x"}, None, None)
    assert _count("GET", "unmatched", 500) == before + 1


async def test_non_http_scope_skipped():
    from app.services.prom_metrics import PrometheusMiddleware

    called = []

    async def inner(scope, receive, send):
        called.append(scope["type"])

    mw = PrometheusMiddleware(inner)
    await mw({"type": "websocket", "path": "/ws"}, None, None)
    await mw({"type": "lifespan"}, None, None)
    assert called == ["websocket", "lifespan"]


async def test_metrics_not_on_app_port(client):
    r = await client.get("/metrics")
    assert "styx_http_request_duration_seconds" not in r.text
    assert "# HELP" not in r.text


def test_template_prefers_effective_context_over_unprefixed_route():
    from types import SimpleNamespace as NS

    from app.services.prom_metrics import _route_template

    scope = {
        "route": NS(path="/{instance_id}"),
        "fastapi": {"effective_route_context": NS(path_format="/api/instances/{instance_id}")},
    }
    assert _route_template(scope) == "/api/instances/{instance_id}"
