"""Append-only audit trail. Call sites must commit (or be committed by caller).

Each event is also written as one ECS JSON line to stdout (``styx.audit``) for the
SIEM. The line goes out on add, before commit: a rolled-back transaction can leave a
line without a row (over-logs, never under-logs; styx-portal#11).
"""
from fastapi import Request

from app.middleware.rate_limit import client_ip_from_headers
from app.models import AuditLog, User
from app.services.audit_ecs import audit_event, emit

_REDACT_KEYS = {"client_secret", "password", "token", "secret", "authorization"}


def _redact(detail):
    if isinstance(detail, dict):
        return {k: ("[redacted]" if k.lower() in _REDACT_KEYS else _redact(v))
                for k, v in detail.items()}
    if isinstance(detail, list):
        return [_redact(v) for v in detail]
    return detail


async def audit(session, action: str, *, user_id: str | None = None,
                actor_ip: str | None = None, resource: str | None = None,
                detail: dict | None = None) -> None:
    row = AuditLog(action=action, user_id=user_id, actor_ip=actor_ip,
                   resource=resource, detail=_redact(detail))
    session.add(row)
    user = await session.get(User, user_id) if user_id else None
    emit(audit_event(action, ts=row.ts, user_id=user_id,
                     user_name=user.username if user else None, actor_ip=actor_ip,
                     resource=resource, detail=row.detail))


async def audit_request(session, request: Request, action: str, *,
                        user_id: str | None = None, resource: str | None = None,
                        detail: dict | None = None) -> None:
    await audit(session, action, user_id=user_id, resource=resource,
                detail=detail, actor_ip=client_ip_from_headers(request))
