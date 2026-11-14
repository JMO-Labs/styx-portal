"""Alertmanager webhook receiver (/internal) and admin ops-alerts API."""
import hmac
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.config import Settings
from app.database import get_session
from app.models import User
from app.models_ops import OpsAlert, OpsState
from app.security.deps import require_admin

internal_router = APIRouter()
router = APIRouter()

def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


SILENT_AFTER = timedelta(minutes=10)


def _ts(v: str | None) -> datetime | None:
    if not v:
        return None
    try:
        d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.year < 1971:  # Alertmanager zero time for firing alerts
        return None
    return d.astimezone(timezone.utc).replace(tzinfo=None)


@internal_router.post("/alerts/alertmanager")
async def alertmanager_webhook(request: Request,
                               session: AsyncSession = Depends(get_session)):
    token = Settings().ALERT_WEBHOOK_TOKEN
    if not token:
        raise HTTPException(503, "Alert webhook disabled")
    auth = request.headers.get("authorization", "")
    scheme, _, supplied = auth.partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
            supplied.encode(), token.encode()):
        raise HTTPException(401, "Invalid token")
    try:
        body = await request.json()
        alerts = body["alerts"]
        assert isinstance(alerts, list)
    except Exception:
        raise HTTPException(422, "Invalid Alertmanager payload")
    now = _now()
    for a in alerts:
        fp = a.get("fingerprint")
        if not fp:
            continue
        labels = a.get("labels") or {}
        row = await session.get(OpsAlert, fp) or OpsAlert(fingerprint=fp, status="firing")
        row.status = "resolved" if a.get("status") == "resolved" else "firing"
        row.labels = labels
        row.annotations = a.get("annotations") or {}
        row.starts_at = _ts(a.get("startsAt"))
        row.ends_at = _ts(a.get("endsAt"))
        row.updated_at = now
        session.add(row)
        if labels.get("alertname") == "Watchdog":
            st = await session.get(OpsState, 1) or OpsState(id=1)
            st.last_watchdog_at = now
            session.add(st)
    await session.commit()
    return {"received": len(alerts)}


@router.get("/ops-alerts")
async def list_ops_alerts(_: User = Depends(require_admin),
                          session: AsyncSession = Depends(get_session)):
    rows = (await session.exec(
        select(OpsAlert).where(OpsAlert.status == "firing")
        .order_by(OpsAlert.updated_at.desc()))).all()
    st = await session.get(OpsState, 1)
    last = st.last_watchdog_at if st else None
    silent = last is None or _now() - last > SILENT_AFTER
    return {
        "monitoring_silent": silent,
        "last_watchdog_at": last,
        "alerts": [{"fingerprint": r.fingerprint, "status": r.status,
                    "labels": r.labels, "annotations": r.annotations,
                    "starts_at": r.starts_at, "ends_at": r.ends_at,
                    "updated_at": r.updated_at} for r in rows],
    }
