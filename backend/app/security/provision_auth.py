"""Provisioning webhook caller auth: mTLS (forwarded cert) + bearer token.

Rejections carry a short code only; no token or fingerprint is logged or returned.
"""
import base64
import binascii
import hashlib
import hmac
import logging

from fastapi import HTTPException, Request

from app.config import Settings

logger = logging.getLogger(__name__)
_settings = Settings()


def _reject(status: int, code: str) -> HTTPException:
    logger.warning("provision auth rejected: %s", code)
    return HTTPException(status_code=status, detail=code)


def _allowed_fingerprints() -> list[str]:
    raw = _settings.PROVISION_CLIENT_CERT_FINGERPRINTS
    return [f.strip().lower() for f in raw.split(",") if f.strip()]


async def require_provision_caller(request: Request) -> None:
    host = request.headers.get("host", "").rsplit(":", 1)[0].lower()
    if not _settings.PROVISION_HOST or host != _settings.PROVISION_HOST.lower():
        raise _reject(404, "bad_host")

    cert = request.headers.get("client-cert")
    if not cert:
        raise _reject(401, "cert_missing")
    try:
        der = base64.b64decode(cert, validate=True)
    except (binascii.Error, ValueError):
        raise _reject(401, "cert_invalid") from None
    fp = hashlib.sha256(der).hexdigest()
    if not any(hmac.compare_digest(fp, a) for a in _allowed_fingerprints()):
        raise _reject(401, "cert_not_allowed")

    auth = request.headers.get("authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _reject(401, "bearer_missing")
    expected = _settings.PROVISION_BEARER_TOKEN
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise _reject(401, "bearer_invalid")
