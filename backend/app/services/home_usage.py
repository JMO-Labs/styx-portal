"""Per-user home PVC usage from Prometheus kubelet volume stats (ADR-0034 / ADR-0044)."""
import logging

import httpx

logger = logging.getLogger("styx-portal")


async def _query(client: httpx.AsyncClient, base: str, metric: str, uid: int) -> int | None:
    promql = f'{metric}{{persistentvolumeclaim="home-{uid}"}}'
    r = await client.get(f"{base.rstrip('/')}/api/v1/query", params={"query": promql})
    r.raise_for_status()
    result = r.json()["data"]["result"]
    return int(float(result[0]["value"][1])) if result else None


async def home_usage(uid: int, prometheus_url: str, *,
                     transport: httpx.AsyncBaseTransport | None = None) -> dict | None:
    """Return {used_bytes, quota_bytes, percent}, or None if unconfigured/unavailable."""
    if not prometheus_url:
        return None
    try:
        async with httpx.AsyncClient(timeout=5.0, transport=transport) as c:
            used = await _query(c, prometheus_url, "kubelet_volume_stats_used_bytes", uid)
            cap = await _query(c, prometheus_url, "kubelet_volume_stats_capacity_bytes", uid)
    except (httpx.HTTPError, KeyError, IndexError, ValueError) as e:
        logger.warning("home usage query failed: %s", type(e).__name__)
        return None
    if used is None or not cap:
        return None
    return {"used_bytes": used, "quota_bytes": cap, "percent": round(used * 100 / cap, 2)}
