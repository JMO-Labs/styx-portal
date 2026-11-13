"""Security-officer alert on takeover start: plain text to a Matrix webhook (ADR-0059)."""
import asyncio
import logging

import httpx

from app.models import SessionTakeover

log = logging.getLogger("styx.takeover_alert")


def build_message(t: SessionTakeover) -> str:
    return (f"Takeover started: actor {t.actor_id} on user {t.user_id or 'unknown'} "
            f"(mode {t.mode}), reason: {t.reason}, started {t.started_at:%Y-%m-%d %H:%M} UTC")


async def notify_start(t: SessionTakeover, url: str,
                       transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Post the alert; True on success. Never raises (except cancellation)."""
    if not url:
        log.info("takeover alert skipped: MATRIX_SECURITY_WEBHOOK_URL unset")
        return False
    text = build_message(t)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10) as c:
            (await c.post(url, json={"text": text, "body": text})).raise_for_status()
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("takeover alert failed: %s", type(e).__name__)
        return False
