"""Prometheus instrumentation: request-duration histogram + internal metrics server.

The metrics endpoint lives on its own port (METRICS_PORT, never routed by
Traefik); nothing here is mounted on the app port.
"""
import logging
import time

import prometheus_client
from prometheus_client import REGISTRY, Counter, Histogram
from starlette.routing import Match
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.services.prom_collectors import DbGaugesCollector

logger = logging.getLogger(__name__)

UNMATCHED = "unmatched"

HTTP_DURATION = Histogram(
    "styx_http_request_duration_seconds",
    "HTTP request duration by method, route template and status",
    ["method", "route", "status"],
)

INSTANCE_LAUNCH_DURATION = Histogram(
    "styx_instance_launch_duration_seconds",
    "Seconds taken by a successful background instance launch",
    buckets=(1, 2, 3, 5, 8, 13, 20, 30, 60, 120, 300),
)
INSTANCE_LAUNCH_FAILURES = Counter(
    "styx_instance_launch_failures_total",
    "Background instance launches that failed",
)

REGISTRY.register(DbGaugesCollector())

_started = False


def start_metrics_server(port: int) -> bool:
    """Start the metrics HTTP server once. port<=0 disables it."""
    global _started
    if port <= 0 or _started:
        return False
    prometheus_client.start_http_server(port)
    _started = True
    logger.info("Prometheus metrics server listening on :%d", port)
    return True


def _route_template(scope: Scope) -> str:
    """Route template for the request; never the raw path (bounded cardinality)."""
    # FastAPI >=0.16x: included routers are resolved lazily; scope["route"] is the
    # unprefixed original route, the prefixed template lives in the effective context.
    ctx = (scope.get("fastapi") or {}).get("effective_route_context")
    path = getattr(ctx, "path_format", None)
    if path:
        return path
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path
    app = scope.get("app")
    for r in getattr(app, "routes", ()):
        try:
            match, _ = r.matches(scope)
        except Exception:  # noqa: BLE001 - never let labelling break a request
            continue
        if match == Match.FULL:
            return getattr(r, "path", UNMATCHED) or UNMATCHED
    return UNMATCHED


class PrometheusMiddleware:
    """Pure ASGI middleware (streaming-safe); only HTTP scopes are observed."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        status = 500
        start = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_DURATION.labels(
                method=scope.get("method", ""),
                route=_route_template(scope),
                status=str(status),
            ).observe(time.perf_counter() - start)
