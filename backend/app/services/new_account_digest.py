"""Daily new-account digest (ADR-0023, ADR-0059): plain text, posted to a Matrix webhook."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.models import User
from app.services import notify_matrix
from app.services.audit import audit

log = logging.getLogger("styx.digest")
INTERVAL_S = 86400


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


async def build_digest(session: AsyncSession, now: datetime) -> str:
    """Accounts created in the last 24 h plus all still-unreviewed ones."""
    since = _utc(now) - timedelta(hours=24)
    users = (await session.exec(select(User).order_by(col(User.created_at).desc()))).all()
    rows = [u for u in users
            if _utc(u.created_at) >= since or (u.reviewed_at is None and not u.disabled_at)]
    if not rows:
        return "New accounts: No new or unreviewed accounts."
    lines = [f"New accounts: {len(rows)} to note"]
    for u in rows:
        state = "disabled" if u.disabled_at else ("reviewed" if u.reviewed_at else "UNREVIEWED")
        lines.append(f"- {u.username} <{u.email or 'no email'}> "
                     f"created {_utc(u.created_at):%Y-%m-%d %H:%M} UTC [{state}]")
    return "\n".join(lines)


async def run_once(session: AsyncSession, url: str, now: datetime | None = None,
                   transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Post the digest; True on success. Never raises (except cancellation)."""
    use_adapter = notify_matrix.configured()
    if not url and not use_adapter:
        log.info("digest skipped: no Matrix target configured")
        return False
    try:
        text = await build_digest(session, now or datetime.now(timezone.utc))
        if use_adapter:
            if not await notify_matrix.send(text, transport=transport):
                raise RuntimeError("matrix notify failed")
            return True
        async with httpx.AsyncClient(transport=transport, timeout=10) as c:
            (await c.post(url, json={"text": text, "body": text})).raise_for_status()
        return True
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        log.warning("digest post failed: %s", type(e).__name__)
        try:
            await audit(session, "account.digest_failed", detail={"error": type(e).__name__})
            await session.commit()
        except Exception:  # noqa: BLE001
            log.warning("digest failure audit failed", exc_info=True)
        return False


async def digest_loop(session_factory) -> None:
    """Leader-only: post once per day."""
    while True:
        async with session_factory() as s:
            await run_once(s, Settings().MATRIX_DIGEST_WEBHOOK_URL)
        await asyncio.sleep(INTERVAL_S)
