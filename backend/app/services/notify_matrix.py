"""Config-gated Matrix room notification adapter. Never raises (except cancellation)."""
import asyncio
import logging
import uuid
from urllib.parse import quote

import httpx

from app.config import Settings

log = logging.getLogger("styx.notify.matrix")


def configured(settings: Settings | None = None) -> bool:
    s = settings or Settings()
    return bool(s.MATRIX_NOTIFY_HOMESERVER and s.MATRIX_NOTIFY_ROOM_ID and s.MATRIX_NOTIFY_TOKEN)


async def send(text: str, settings: Settings | None = None,
               transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Post `text` to the configured room; False when disabled or on any failure."""
    s = settings or Settings()
    if not configured(s):
        return False
    url = (f"{s.MATRIX_NOTIFY_HOMESERVER.rstrip('/')}/_matrix/client/v3/rooms/"
           f"{quote(s.MATRIX_NOTIFY_ROOM_ID, safe='')}/send/m.room.message/{uuid.uuid4().hex}")
    try:
        async with httpx.AsyncClient(transport=transport, timeout=10) as c:
            r = await c.put(url, json={"msgtype": "m.text", "body": text},
                            headers={"Authorization": f"Bearer {s.MATRIX_NOTIFY_TOKEN}"})
            r.raise_for_status()
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001 - never log the exception text (may embed URL/token)
        log.warning("matrix notify failed: %s", type(e).__name__)
        return False
